#

from tkinter import *
from tkinter import ttk

from hoppie_station import *


def main_gui():

    # NOTE: these are hacky way for timed events w/tkinter
    def msg_timer_func():
        while not msg_q.empty():
            msgbox.insert('end', msg_q.get())
            msgbox.see('end')
        root.after(500, msg_timer_func)  # update once per second

    def update_timer_func(wait_s, fast_polls):
        entries = receive_msg()  # will mark station as online
        last_update.set(
            f"[{hoppie_station}] Last updated: {datetime.now().isoformat()[:-7]}")
        msg_sent = False
        if auto_process.get():  # only process messages if flag set
            for (sender, packet_type, packet) in entries:
                m = None
                if packet_type == "cpdlc":
                    m = process_cpdlc_msg(sender, packet)
                elif packet_type == "telex":
                    pass
                if m is not None:
                    msg_sent = True
        fast_polls = 6 if msg_sent else max(0, fast_polls - 1)
        next_wait_s = (20 if fast_polls > 0 else randint(45, 75))
        root.after(wait_s * 1000,
                   lambda: update_timer_func(next_wait_s, fast_polls))

    def send_msg_gui():
        recipient = recipient_entry.get().upper()
        message = textbox.get("1.0", "end").upper()
        if len(recipient) == 0 or len(message) == 0:
            return
        _ = send_msg(recipient, msg_type.get(), message)
        textbox.delete("1.0", "end")

    root = Tk()
    root.title(f"Hoppie ACARS Station: {hoppie_station}")
    mainframe = ttk.Frame(root, padding="10 10 10 10")
    mainframe.grid(column=0, row=0, sticky="NESW")
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)

    # status and autoreply
    last_update = StringVar()
    Label(mainframe, textvariable=last_update, width=30, justify=LEFT).grid(
        column=1, columnspan=3, row=0, sticky="W")
    auto_process = BooleanVar(value=True)
    auto_chk = ttk.Checkbutton(mainframe, text="Auto-Reply",
                               variable=auto_process,
                               onvalue=True, offvalue=False)
    auto_chk.grid(column=6, columnspan=2, row=0, sticky="E")

    # message box
    msgbox = Listbox(mainframe, height=10, width=80, font="TkFixedFont",
                     borderwidth=3, relief="groove")
    msgbox.grid(column=1, row=1, sticky="NESW", columnspan=7, pady=5)

    # input box
    textbox = Text(mainframe, height=3, width=80, font="TkFixedFont",
                   borderwidth=3, relief="sunken")
    textbox.grid(column=1, row=2, sticky="NESW", columnspan=7, pady=5)

    # send controls
    Label(mainframe, width=30).grid(column=1, row=3, columnspan=2)
    Label(mainframe, text="Recipient:", justify=RIGHT).grid(
        column=3, row=3, sticky="E")
    recipient_entry = ttk.Entry(mainframe, width=8, font="TkFixedFont")
    recipient_entry.grid(column=4, row=3, sticky="E")

    Label(mainframe, text="Type:", justify=RIGHT).grid(
        column=5, row=3, sticky="E")
    msg_type = StringVar()
    msg_type.set("telex")
    msg_type_sel = ttk.Combobox(mainframe, textvariable=msg_type, width=5)
    msg_type_sel['values'] = ["cpdlc", "telex"]
    msg_type_sel.grid(column=6, row=3, sticky="E")
    msg_type_sel.state(["readonly"])
    send_btn = Button(mainframe, text="Send", command=send_msg_gui)
    send_btn.grid(column=7, row=3, sticky="E")

    msg_timer_func()
    update_timer_func(20, 0)
    root.mainloop()


if __name__ == "__main__":
    main_gui()
