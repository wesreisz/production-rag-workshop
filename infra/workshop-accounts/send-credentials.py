#!/usr/bin/env python3
import os
import smtplib
import sys
from email.mime.text import MIMEText


def send(sender_email, app_password, recipient_email, credentials_file):
    with open(credentials_file) as f:
        body = f.read()

    student_label = os.path.basename(credentials_file).replace("-credentials.txt", "")

    msg = MIMEText(body)
    msg["Subject"] = f"Your AWS Workshop Credentials ({student_label})"
    msg["From"] = sender_email
    msg["To"] = recipient_email

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender_email, app_password)
        server.sendmail(sender_email, recipient_email, msg.as_string())

    print(f"  -> Credentials emailed to {recipient_email}")


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print("Usage: send-credentials.py <sender_email> <app_password> <recipient_email> <credentials_file>")
        sys.exit(1)

    send(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
