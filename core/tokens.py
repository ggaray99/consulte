"""Signed tokens for unauthenticated patient self-service flows.

Same primitive as the review-token flow (see REVIEW_TOKEN_SALT in views.py).
Lives in its own module to keep emails.py and views.py from importing each other.
"""
from django.core import signing

from .models import Appointment

PATIENT_TOKEN_SALT = 'consulte.appointment.patient'
PATIENT_TOKEN_MAX_AGE = 365 * 24 * 60 * 60  # 1 year — covers any reasonable booking horizon


def make_patient_token(appointment):
    return signing.TimestampSigner(salt=PATIENT_TOKEN_SALT).sign(str(appointment.id))


def parse_patient_token(token):
    try:
        appointment_id = signing.TimestampSigner(salt=PATIENT_TOKEN_SALT).unsign(
            token, max_age=PATIENT_TOKEN_MAX_AGE
        )
    except signing.BadSignature:
        return None
    return Appointment.objects.filter(id=appointment_id).first()
