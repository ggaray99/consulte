"""Transactional email via Resend.

Booking flow must never fail because of email — every send is wrapped in
try/except and logs the error. If RESEND_API_KEY is empty (dev, CI), the
function is a no-op.
"""
import logging

from django.conf import settings
from django.template.loader import render_to_string
from django.urls import reverse

from .tokens import make_patient_token

logger = logging.getLogger(__name__)


def _absolute_landing_url(professional, request=None):
    path = reverse('public_landing', kwargs={'slug': professional.slug})
    if request is not None:
        return request.build_absolute_uri(path)
    if settings.SITE_BASE_URL:
        return f'{settings.SITE_BASE_URL}{path}'
    return ''


def _absolute_profile_image_url(professional, request=None):
    if not professional.profile_image:
        return ''
    url = professional.profile_image.url
    if request is not None:
        return request.build_absolute_uri(url)
    if settings.SITE_BASE_URL:
        return f'{settings.SITE_BASE_URL}{url}'
    return ''


def _absolute_patient_url(appointment, request=None):
    path = reverse('patient_appointment', kwargs={'token': make_patient_token(appointment)})
    if request is not None:
        return request.build_absolute_uri(path)
    if settings.SITE_BASE_URL:
        return f'{settings.SITE_BASE_URL}{path}'
    return ''


def send_clinic_invitation(invitation, request=None):
    """Send an invitation email to a professional joining a clinic.

    Returns True if accepted by Resend, False otherwise. Never raises.
    """
    api_key = settings.RESEND_API_KEY
    if not api_key:
        logger.info('Resend API key not set, skipping clinic invitation email.')
        return False

    organization = invitation.organization
    join_path = reverse('clinic_join', kwargs={'token': invitation.token})
    if request is not None:
        join_url = request.build_absolute_uri(join_path)
    elif settings.SITE_BASE_URL:
        join_url = f'{settings.SITE_BASE_URL}{join_path}'
    else:
        join_url = join_path

    # Owner name for a personal-feeling subject and a real Reply-To.
    # Personal subjects land in Inbox more often than generic "we invited you" lines.
    owner_name = ''
    owner_email = ''
    if invitation.invited_by:
        owner_email = invitation.invited_by.email
        owner_pro = getattr(invitation.invited_by, 'professional', None)
        owner_name = owner_pro.professional_name if owner_pro else owner_email

    context = {
        'invitation': invitation,
        'organization': organization,
        'join_url': join_url,
        'owner_name': owner_name,
    }

    if owner_name:
        subject = f'{owner_name} te invita a sumarte a {organization.name}'
    else:
        subject = f'Invitación a {organization.name}'

    html_body = render_to_string('core/emails/clinic_invitation.html', context)
    text_body = render_to_string('core/emails/clinic_invitation.txt', context)

    try:
        import resend
        resend.api_key = api_key
        payload = {
            'from': settings.DEFAULT_FROM_EMAIL,
            'to': [invitation.email],
            'subject': subject,
            'html': html_body,
            'text': text_body,
            'headers': {
                'X-Entity-Ref-ID': str(invitation.id),
            },
        }
        if owner_email:
            payload['reply_to'] = [owner_email]
        resend.Emails.send(payload)
        return True
    except Exception:
        logger.exception('Failed to send clinic invitation email')
        return False


def send_appointment_confirmation(appointment, request=None):
    """Send the brand-book slide-20 confirmation email to the patient.

    Returns True if the API accepted the message, False otherwise (missing
    API key, missing patient email, or API error). Never raises.
    """
    api_key = settings.RESEND_API_KEY
    if not api_key:
        logger.info('Resend API key not set, skipping confirmation email.')
        return False

    patient = appointment.patient
    if not patient.email:
        return False

    professional = appointment.professional
    context = {
        'appointment': appointment,
        'patient': patient,
        'professional': professional,
        'landing_url': _absolute_landing_url(professional, request),
        'profile_image_url': _absolute_profile_image_url(professional, request),
        'manage_url': _absolute_patient_url(appointment, request),
    }

    subject = (
        f'Turno confirmado — {professional.professional_name} · '
        f'{appointment.appointment_date.strftime("%d/%m/%Y")} '
        f'{appointment.appointment_time.strftime("%H:%M")}'
    )
    html_body = render_to_string('core/emails/appointment_confirmation.html', context)
    text_body = render_to_string('core/emails/appointment_confirmation.txt', context)

    try:
        import resend
        resend.api_key = api_key
        resend.Emails.send({
            'from': settings.DEFAULT_FROM_EMAIL,
            'to': [patient.email],
            'subject': subject,
            'html': html_body,
            'text': text_body,
        })
        return True
    except Exception:
        logger.exception('Failed to send appointment confirmation email')
        return False


def send_cancellation_to_pro(appointment, request=None):
    """Notify the professional when a patient self-cancels their turn."""
    api_key = settings.RESEND_API_KEY
    if not api_key:
        logger.info('Resend API key not set, skipping pro cancellation email.')
        return False

    professional = appointment.professional
    if not professional.email:
        return False

    patient = appointment.patient
    context = {
        'appointment': appointment,
        'patient': patient,
        'professional': professional,
    }

    subject = (
        f'Paciente canceló — {patient.first_name} {patient.last_name} · '
        f'{appointment.appointment_date.strftime("%d/%m/%Y")} '
        f'{appointment.appointment_time.strftime("%H:%M")}'
    )
    html_body = render_to_string('core/emails/appointment_cancelled_pro.html', context)
    text_body = render_to_string('core/emails/appointment_cancelled_pro.txt', context)

    try:
        import resend
        resend.api_key = api_key
        resend.Emails.send({
            'from': settings.DEFAULT_FROM_EMAIL,
            'to': [professional.email],
            'subject': subject,
            'html': html_body,
            'text': text_body,
        })
        return True
    except Exception:
        logger.exception('Failed to send cancellation email to pro')
        return False


def send_reschedule_to_pro(appointment, old_date, old_time, request=None):
    """Notify the professional when a patient self-reschedules their turn."""
    api_key = settings.RESEND_API_KEY
    if not api_key:
        logger.info('Resend API key not set, skipping pro reschedule email.')
        return False

    professional = appointment.professional
    if not professional.email:
        return False

    patient = appointment.patient
    context = {
        'appointment': appointment,
        'patient': patient,
        'professional': professional,
        'old_date': old_date,
        'old_time': old_time,
    }

    subject = (
        f'Paciente reagendó — {patient.first_name} {patient.last_name} · '
        f'antes {old_date.strftime("%d/%m")} {old_time.strftime("%H:%M")} → '
        f'ahora {appointment.appointment_date.strftime("%d/%m")} '
        f'{appointment.appointment_time.strftime("%H:%M")}'
    )
    html_body = render_to_string('core/emails/appointment_rescheduled_pro.html', context)
    text_body = render_to_string('core/emails/appointment_rescheduled_pro.txt', context)

    try:
        import resend
        resend.api_key = api_key
        resend.Emails.send({
            'from': settings.DEFAULT_FROM_EMAIL,
            'to': [professional.email],
            'subject': subject,
            'html': html_body,
            'text': text_body,
        })
        return True
    except Exception:
        logger.exception('Failed to send reschedule email to pro')
        return False
