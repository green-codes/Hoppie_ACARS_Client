#

import sys
import re
from random import randint
import time
from datetime import datetime, timedelta
import requests
from queue import SimpleQueue

# config
hoppie_url = "http://www.hoppie.nl/acars/system/connect.html"
hoppie_logon = "nZMVH56rpANeUC"
hoppie_station = "EQCA"
displayed_packet_types = {
    "progress": True,
    "cpdlc": True,
    "telex": True,
    "ping": False,
    "posreq": False,
    "position": True,
    "datareq": False,
    "poll": False,
    "peek": False,
}

# trackers
msg_q = SimpleQueue()  # queue for messages to be displayed


def generate_squawk():
    # range: 1000-6777
    squawk = randint(1, 6) * 1000
    for i in range(3):
        squawk += randint(0, 7) * (10**i)
    return squawk


def send_msg(recipient, packet_type, packet):
    if displayed_packet_types[packet_type]:
        msg_q.put(
            f"{datetime.now().isoformat()[:-7]} >>> {recipient} {packet_type} {packet}"
        )
    r = requests.post(
        hoppie_url,
        {
            "logon": hoppie_logon,
            "from": hoppie_station,
            "to": recipient,
            "type": packet_type,
            "packet": packet,
        },
    )
    if not r.ok:  # this error should go all the way to the top
        raise RuntimeError(f"Disconnected: {r} {r.text}")
    return r  # NOTE: only returns if send successful


def receive_msg():
    r = send_msg("SERVER", "poll", "")  # "peek" to get all msgs, else "poll"

    end_of_last_entry = 0
    entries = []
    while True:
        next_entry_start_pos = r.text[end_of_last_entry:].find("{")
        if next_entry_start_pos < 0:
            break  # no more messages

        entry_start_pos = end_of_last_entry + next_entry_start_pos
        msg_start_pos = entry_start_pos + 1 + r.text[entry_start_pos + 1 :].find("{")
        msg_stop_pos = msg_start_pos + 1 + r.text[msg_start_pos + 1 :].find("}")
        entry_stop_pos = msg_stop_pos + 1 + r.text[msg_stop_pos + 1 :].find("}")

        metadata = r.text[entry_start_pos + 1 : msg_start_pos].strip().split(" ")
        sender = metadata[0]
        packet_type = metadata[1]
        packet = r.text[msg_start_pos + 1 : msg_stop_pos].strip()

        entries += [(sender, packet_type, packet)]
        end_of_last_entry = entry_stop_pos + 1

        if displayed_packet_types[packet_type]:
            msg_q.put(
                f"{datetime.now().isoformat()[:-7]} <<< {sender} {packet_type} {packet}"
            )

    return entries


def send_cpdlc(recipient, message, mrn="", response="NE"):
    # mrn: ID of message to respond to
    # response: specifies how the recipient should respond
    #           list: WU, AN, R, NE
    station_msg_id = randint(150, 950)
    packet = f"/data2/{station_msg_id}/{mrn}/{response}/{message}"
    _ = send_msg(recipient, "cpdlc", packet)  # send ok, discard reply
    return (recipient, "cpdlc", packet)  # for processing


def process_cpdlc_msg(sender, packet):
    # should return the server response if sent, or None if no reply necessary

    try:  # parse CPDLC message
        assert packet.startswith("/data2/")
        msg_id, mrn, response, msg = tuple(
            [
                e.strip().upper()
                for e in packet.replace("/data2/", "").split("/", maxsplit=3)
            ]
        )
    except Exception as e:
        msg_q.put(f"Invalid CPDLC payload from {sender}: {packet}")
        return None

    if response == "Y":  # sender asked for response

        if "REQUEST LOGON" in msg:
            return send_cpdlc(sender, "LOGON ACCEPTED", msg_id, "NE")

        elif msg.startswith("REQUEST"):
            msg = msg.replace("REQUEST", "").strip()

            # vertical nav
            if msg.startswith("CLB"):
                req = msg.replace("CLB TO", "").strip().split(" ")
                at_alt = " ".join(req[1:]) + " " if "AT" in req else ""
                return send_cpdlc(
                    sender, f"{at_alt}CLIMB TO AND MAINTAIN @{req[0]}@", msg_id, "WU"
                )
            elif msg.startswith("DES"):
                req = msg.replace("DES TO", "").strip().split(" ")
                at_alt = " ".join(req[1:]) + " " if "AT" in req else ""
                return send_cpdlc(
                    sender, f"{at_alt}DESCEND TO AND MAINTAIN @{req[0]}@", msg_id, "WU"
                )
            elif msg.startswith("OWN SEPARATION"):
                return send_cpdlc(
                    sender, "MAINTAIN OWN SEPARATION AND VMC", msg_id, "WU"
                )

            # lateral nav
            elif msg.startswith("DIRECT TO"):
                dest = msg.replace("DIRECT TO", "").strip()
                return send_cpdlc(sender, f"PROCEED DIRECT TO @{dest}@", msg_id, "WU")
            elif msg.startswith("HEADING"):
                heading = msg.replace("HEADING", "").strip()
                return send_cpdlc(sender, f"FLY HEADING @{heading}@", msg_id, "WU")
            elif msg.startswith("GROUND TRACK"):
                heading = msg.replace("GROUND TRACK", "").strip()
                return send_cpdlc(sender, f"FLY GROUND TRACK @{heading}@", msg_id, "WU")
            elif ("DEVIATION" in msg) or ("OFFSET" in msg):
                return send_cpdlc(sender, "REPORT BACK ON ROUTE", msg_id, "R")

            else:  # try to match request type

                match = re.search("([A-Z]{4})-([A-Z]{4})", msg)
                if match:  # route request
                    departure_icao, arrival_icao = match.groups()
                    route = msg[match.span()[-1] :].strip().split(".")
                    route = " ".join(route[1:-1])
                    squawk = generate_squawk()
                    return send_cpdlc(
                        sender,
                        f"CLEARED TO @{arrival_icao}@ VIA @{route}@ SQUAWK @{squawk}@",
                        msg_id,
                        "WU",
                    )

                match = re.search("([A-Z]{3,5}[0-9]{1,2}[A-Z]{1,2})", msg)
                if match:  # SID/STAR procedure request
                    return send_cpdlc(sender, f"CLEARED @{msg}@", msg_id, "WU")

                match = re.search("([0-9]{3}KT)", msg)
                if match:  # speed
                    return send_cpdlc(sender, f"MAINTAIN @{match.groups()[0]}@")

                match = re.search("(FL[0-9]{3}|[0-9]{3,5})", msg)
                if match:  # altitude
                    return send_cpdlc(sender, f"MAINTAIN @{match.groups()[0]}@")

                # no match
                return send_cpdlc(sender, "SERVICE UNAVAILABLE", msg_id, "NE")

        elif "BACK ON ROUTE" in msg:
            return send_cpdlc(sender, "PROCEED BACK ON ROUTE", msg_id, "WU")

        elif "WHEN CAN WE EXPECT" in msg:
            msg = msg.replace("WHEN CAN WE EXPECT", "").strip()
            req_time = datetime.utcnow() + timedelta(minutes=randint(2, 5))

            if "HIGHER ALT" in msg:
                return send_cpdlc(
                    sender,
                    f"EXPECT CLIMB AT @{req_time.hour:02d}{req_time.minute:02d}Z@",
                    msg_id,
                    "R",
                )

            elif "LOWER ALT" in msg:
                return send_cpdlc(
                    sender,
                    f"EXPECT DESCENT AT @{req_time.hour:02d}{req_time.minute:02d}Z@",
                    msg_id,
                    "R",
                )

            else:  # no match
                return send_cpdlc(sender, "SERVICE UNAVAILABLE", msg_id, "NE")

        else:  # no match
            return send_cpdlc(sender, "SERVICE UNAVAILABLE", msg_id, "NE")

    else:  # sender did not ask for response

        if "POSITION REPORT" in msg:
            pass  # TODO: only useful for actual ATC

        elif "LOGOFF" in msg:
            pass  # TODO

        return None


def main_headless():
    fast_polls = 0  # number of fast pools remaining
    while True:
        entries = receive_msg()  # will mark station as online
        msg_sent = False
        for sender, packet_type, packet in entries:
            m = None
            if packet_type == "cpdlc":
                m = process_cpdlc_msg(sender, packet)
            elif packet_type == "telex":
                pass
            if m is not None:
                msg_sent = True
        while not msg_q.empty():
            print(msg_q.get())
        fast_polls = 6 if msg_sent else (fast_polls - 1)
        time.sleep(20 if (fast_polls > 0) else randint(45, 75))


if __name__ == "__main__":
    main_headless()
