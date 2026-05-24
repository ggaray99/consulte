import io
import base64
from datetime import datetime, timedelta, date

import qrcode
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, Http404
from django.contrib import messages
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core import signing
from django.db.models import Q, Count
from django.urls import reverse
from django.utils import timezone

from .models import (
    Professional, Patient, Appointment, Organization, OrganizationInvitation,
    Subscription,
    LandingStat, LandingCredential, LandingService, LandingTestimonial,
    VERTICAL_CHOICES,
)
from .forms import (
    ProfessionalSetupForm, BookingPatientForm, PatientForm,
    MissionForm, LandingSettingsForm, BasicsForm, SocialLinksForm,
    LandingStatForm, LandingCredentialForm,
    LandingServiceForm, LandingTestimonialForm, PublicReviewForm,
    OrganizationSetupForm, OrganizationBrandingForm, InvitationForm, JoinClinicForm,
)
from .emails import (
    send_appointment_confirmation, send_clinic_invitation,
    send_cancellation_to_pro, send_reschedule_to_pro,
)
from .tokens import parse_patient_token
from django.views.decorators.http import require_POST


REVIEW_TOKEN_SALT = 'consulte.appointment.review'
REVIEW_TOKEN_MAX_AGE = 60 * 24 * 60 * 60  # 60 days


def make_review_token(appointment):
    return signing.TimestampSigner(salt=REVIEW_TOKEN_SALT).sign(str(appointment.id))


def parse_review_token(token):
    try:
        appointment_id = signing.TimestampSigner(salt=REVIEW_TOKEN_SALT).unsign(
            token, max_age=REVIEW_TOKEN_MAX_AGE
        )
    except signing.BadSignature:
        return None
    return Appointment.objects.filter(id=appointment_id).first()


# --- Helpers ---

def get_professional(request):
    """Get the professional linked to the logged-in user."""
    try:
        return request.user.professional
    except Professional.DoesNotExist:
        return None


def generate_qr_base64(url):
    qr = qrcode.make(url, box_size=6, border=2)
    buffer = io.BytesIO()
    qr.save(buffer, format='PNG')
    return base64.b64encode(buffer.getvalue()).decode()


def get_available_slots(professional, target_date):
    start = datetime.combine(target_date, professional.start_time)
    end = datetime.combine(target_date, professional.end_time)
    duration = timedelta(minutes=professional.appointment_duration_minutes)

    existing = set(
        Appointment.objects.filter(
            professional=professional,
            appointment_date=target_date,
            status__in=['scheduled', 'confirmed']
        ).values_list('appointment_time', flat=True)
    )

    slots = []
    current = start
    while current + duration <= end:
        t = current.time()
        if t not in existing:
            slots.append(t)
        current += duration
    return slots


DAYS_MAP = {
    'lunes': 0, 'martes': 1, 'miercoles': 2, 'miércoles': 2,
    'jueves': 3, 'viernes': 4, 'sabado': 5, 'sábado': 5, 'domingo': 6,
}

DAYS_LIST = ['lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado', 'domingo']


# --- Public Views ---

def home(request):
    demo_professional = Professional.objects.order_by('created_at').first()
    is_pro = request.user.is_authenticated and hasattr(request.user, 'professional')
    return render(request, 'core/home.html', {
        'demo_professional': demo_professional,
        'is_pro': is_pro,
    })


def pricing(request):
    is_pro = request.user.is_authenticated and hasattr(request.user, 'professional')
    return render(request, 'core/pricing.html', {
        'is_pro': is_pro,
    })


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')

        # Django auth uses username, we find user by email
        try:
            user_obj = User.objects.get(email=email)
            user = authenticate(request, username=user_obj.username, password=password)
        except User.DoesNotExist:
            user = None

        if user is not None:
            login(request, user)
            next_url = request.GET.get('next', 'dashboard')
            return redirect(next_url)
        else:
            return render(request, 'core/login.html', {'error': 'Email o contraseña incorrectos.'})

    return render(request, 'core/login.html')


def logout_view(request):
    logout(request)
    return redirect('home')


def setup(request):
    if request.user.is_authenticated and hasattr(request.user, 'professional'):
        return redirect('dashboard')

    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        password_confirm = request.POST.get('password_confirm', '')

        errors = []

        if not password or len(password) < 6:
            errors.append('La contraseña debe tener al menos 6 caracteres.')
        if password != password_confirm:
            errors.append('Las contraseñas no coinciden.')
        if User.objects.filter(email=email).exists():
            errors.append('Ya existe una cuenta con ese email.')

        working_days = ','.join(request.POST.getlist('working_days'))
        post_data = request.POST.copy()
        post_data['accepts_insurance'] = 'accepts_insurance' in request.POST
        post_data['accepts_private'] = 'accepts_private' in request.POST
        form = ProfessionalSetupForm(post_data, request.FILES)

        if form.is_valid() and not errors:
            # Create User
            user = User.objects.create_user(
                username=email,
                email=email,
                password=password,
            )
            # Create Professional linked to User
            professional = form.save(commit=False)
            professional.user = user
            professional.working_days = working_days
            professional.save()

            login(request, user)
            messages.success(request, 'Tu consultorio ya está online.')
            return redirect('dashboard')

        form_errors = [e for field_errors in form.errors.values() for e in field_errors]
        errors.extend(form_errors)
        return render(request, 'core/setup.html', {'form': form, 'days': DAYS_LIST, 'errors': errors})

    form = ProfessionalSetupForm()
    return render(request, 'core/setup.html', {'form': form, 'days': DAYS_LIST})


# --- Dashboard Views (all require login) ---

@login_required
def dashboard(request):
    professional = get_professional(request)
    if not professional:
        return redirect('setup')

    today = date.today()
    now = datetime.now()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    month_start = today.replace(day=1)

    appointments_today = list(Appointment.objects.filter(
        professional=professional,
        appointment_date=today
    ).select_related('patient').order_by('appointment_time'))

    upcoming = list(Appointment.objects.filter(
        professional=professional,
        appointment_date__gt=today,
        status__in=['scheduled', 'confirmed']
    ).select_related('patient').order_by('appointment_date', 'appointment_time')[:10])

    week_count = Appointment.objects.filter(
        professional=professional,
        appointment_date__range=(week_start, week_end),
        status__in=['scheduled', 'confirmed', 'completed'],
    ).count()
    month_count = Appointment.objects.filter(
        professional=professional,
        appointment_date__gte=month_start,
        appointment_date__lte=today,
        status__in=['scheduled', 'confirmed', 'completed'],
    ).count()
    cancelled_count = Appointment.objects.filter(
        professional=professional,
        appointment_date__gte=month_start,
        status='cancelled',
    ).count()

    recent_patients = Patient.objects.filter(professional=professional).order_by('-created_at')[:5]

    public_url = request.build_absolute_uri(f'/p/{professional.slug}/')
    qr_data = generate_qr_base64(public_url)

    # Tag each today appointment with helper flags + an optional review link
    # so the timeline can highlight the next one and offer a copy button.
    next_appointment = None
    for apt in appointments_today:
        apt.review_link = ''
        if apt.status == 'completed' and not hasattr(apt, 'testimonial'):
            apt.review_link = request.build_absolute_uri(
                reverse('public_review', kwargs={'slug': professional.slug, 'token': make_review_token(apt)})
            )
        apt.is_next = False
        apt.is_past = apt.status in ('completed', 'cancelled') or (
            apt.appointment_time < now.time()
        )

    for apt in appointments_today:
        if not apt.is_past and apt.status in ('scheduled', 'confirmed'):
            apt.is_next = True
            next_appointment = apt
            break

    if next_appointment is None and upcoming:
        next_appointment = upcoming[0]

    minutes_until_next = None
    if next_appointment is not None:
        apt_dt = datetime.combine(next_appointment.appointment_date, next_appointment.appointment_time)
        delta_seconds = (apt_dt - now).total_seconds()
        if delta_seconds > 0:
            minutes_until_next = int(delta_seconds // 60)

    return render(request, 'core/dashboard.html', {
        'professional': professional,
        'appointments_today': appointments_today,
        'upcoming': upcoming,
        'recent_patients': recent_patients,
        'public_url': public_url,
        'qr_data': qr_data,
        'today': today,
        'now': now,
        'today_count': len(appointments_today),
        'week_count': week_count,
        'month_count': month_count,
        'cancelled_count': cancelled_count,
        'next_appointment': next_appointment,
        'minutes_until_next': minutes_until_next,
        'status_choices': Appointment.STATUS_CHOICES,
    })


@login_required
def appointment_new(request):
    professional = get_professional(request)
    if not professional:
        return redirect('setup')

    if request.method == 'POST':
        patient_id = request.POST.get('patient_id')
        patient = None

        if patient_id:
            patient = Patient.objects.filter(id=patient_id, professional=professional).first()

        if not patient:
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()
            phone = request.POST.get('phone', '').strip()
            if first_name and last_name and phone:
                patient, _ = Patient.objects.update_or_create(
                    professional=professional,
                    phone=phone,
                    defaults={'first_name': first_name, 'last_name': last_name, 'email': request.POST.get('email', '')}
                )

        if patient:
            apt_date = request.POST.get('appointment_date')
            apt_time = request.POST.get('appointment_time')
            try:
                d = datetime.strptime(apt_date, '%Y-%m-%d').date()
                t = datetime.strptime(apt_time, '%H:%M').time()
                if Appointment.objects.filter(
                    professional=professional, appointment_date=d, appointment_time=t,
                    status__in=['scheduled', 'confirmed']
                ).exists():
                    messages.error(request, 'Ya existe un turno en ese horario.')
                else:
                    posted_mode = request.POST.get('mode', '')
                    if professional.both_modes:
                        mode = posted_mode if posted_mode in ('online', 'presencial') else 'presencial'
                    elif professional.supports_online:
                        mode = 'online'
                    else:
                        mode = 'presencial'

                    Appointment.objects.create(
                        professional=professional, patient=patient,
                        appointment_date=d, appointment_time=t,
                        reason=request.POST.get('reason', ''),
                        status=request.POST.get('status', 'scheduled'),
                        source='manual',
                        mode=mode,
                    )
                    messages.success(request, 'Turno creado correctamente.')
                    return redirect('dashboard')
            except (ValueError, TypeError):
                messages.error(request, 'Fecha u hora inválida.')

    patients = Patient.objects.filter(professional=professional).order_by('last_name', 'first_name')
    return render(request, 'core/appointment_new.html', {
        'professional': professional,
        'patients': patients,
        'status_choices': Appointment.STATUS_CHOICES,
    })


@login_required
def appointment_detail(request, appointment_id):
    professional = get_professional(request)
    if not professional:
        return redirect('setup')

    appointment = get_object_or_404(Appointment, id=appointment_id, professional=professional)

    if request.method == 'POST':
        action = request.POST.get('action', '')
        if action == 'save_notes':
            appointment.notes = request.POST.get('notes', '')
            appointment.save(update_fields=['notes', 'updated_at'])
            messages.success(request, 'Notas guardadas.')
            return redirect('appointment_detail', appointment_id=appointment.id)
        if action == 'update_status':
            new_status = request.POST.get('status')
            if new_status in dict(Appointment.STATUS_CHOICES):
                appointment.status = new_status
                appointment.save(update_fields=['status', 'updated_at'])
                messages.success(request, 'Estado actualizado.')
            return redirect('appointment_detail', appointment_id=appointment.id)

    # Histórico: últimos 5 turnos previos del mismo paciente (no este)
    history = Appointment.objects.filter(
        professional=professional, patient=appointment.patient
    ).exclude(id=appointment.id).order_by('-appointment_date', '-appointment_time')[:5]

    return render(request, 'core/appointment_detail.html', {
        'professional': professional,
        'appointment': appointment,
        'history': history,
        'status_choices': Appointment.STATUS_CHOICES,
    })


@login_required
def appointment_status(request, appointment_id):
    professional = get_professional(request)
    if not professional:
        return redirect('setup')

    appointment = get_object_or_404(Appointment, id=appointment_id, professional=professional)
    new_status = request.POST.get('status')
    if new_status in dict(Appointment.STATUS_CHOICES):
        appointment.status = new_status
        appointment.save()
    return redirect('dashboard')


@login_required
def patient_list(request):
    professional = get_professional(request)
    if not professional:
        return redirect('setup')

    q = request.GET.get('q', '')
    patients = Patient.objects.filter(professional=professional)
    if q:
        patients = patients.filter(
            Q(first_name__icontains=q) | Q(last_name__icontains=q) |
            Q(phone__icontains=q) | Q(email__icontains=q)
        )
    patients = patients.order_by('last_name', 'first_name')

    return render(request, 'core/patient_list.html', {
        'professional': professional,
        'patients': patients,
        'q': q,
    })


@login_required
def patient_detail(request, patient_id):
    professional = get_professional(request)
    if not professional:
        return redirect('setup')

    patient = get_object_or_404(Patient, id=patient_id, professional=professional)
    appointments = Appointment.objects.filter(patient=patient).order_by('-appointment_date', '-appointment_time')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'update_info':
            form = PatientForm(request.POST, instance=patient)
            if form.is_valid():
                form.save()
                messages.success(request, 'Datos actualizados.')
                return redirect('patient_detail', patient_id=patient.id)

        elif action == 'update_notes':
            patient.clinical_notes = request.POST.get('clinical_notes', '')
            patient.save()
            messages.success(request, 'Notas clínicas actualizadas.')
            return redirect('patient_detail', patient_id=patient.id)

    return render(request, 'core/patient_detail.html', {
        'professional': professional,
        'patient': patient,
        'appointments': appointments,
    })


@login_required
def patient_new(request):
    professional = get_professional(request)
    if not professional:
        return redirect('setup')

    if request.method == 'POST':
        form = PatientForm(request.POST)
        if form.is_valid():
            patient = form.save(commit=False)
            patient.professional = professional
            patient.save()
            messages.success(request, 'Paciente creado.')
            return redirect('patient_detail', patient_id=patient.id)
    else:
        form = PatientForm()

    return render(request, 'core/patient_new.html', {
        'professional': professional,
        'form': form,
    })


@login_required
def patient_search_api(request):
    professional = get_professional(request)
    if not professional:
        return JsonResponse([], safe=False)

    q = request.GET.get('q', '')
    if len(q) < 2:
        return JsonResponse([], safe=False)

    patients = Patient.objects.filter(
        professional=professional
    ).filter(
        Q(first_name__icontains=q) | Q(last_name__icontains=q) |
        Q(phone__icontains=q) | Q(email__icontains=q)
    )[:10]

    results = [{'id': str(p.id), 'name': f'{p.first_name} {p.last_name}', 'phone': p.phone} for p in patients]
    return JsonResponse(results, safe=False)


# --- Landing Admin (per-professional editor) ---

LANDING_SECTIONS = {
    'stat':        (LandingStat,         LandingStatForm,         'landing_stats'),
    'credential':  (LandingCredential,   LandingCredentialForm,   'landing_credentials'),
    'service':     (LandingService,      LandingServiceForm,      'landing_services'),
    'testimonial': (LandingTestimonial,  LandingTestimonialForm,  'landing_testimonials'),
}


@login_required
def landing_admin(request):
    professional = get_professional(request)
    if not professional:
        return redirect('setup')

    if request.method == 'POST':
        action = request.POST.get('action', '')

        if action == 'mission_save':
            form = MissionForm(request.POST, instance=professional)
            if form.is_valid():
                form.save()
                messages.success(request, 'Misión actualizada.')
            return redirect('/dashboard/landing/#mission')

        if action == 'settings_save':
            form = LandingSettingsForm(request.POST, instance=professional)
            if form.is_valid():
                form.save()
                messages.success(request, 'Ajustes de landing guardados.')
            else:
                messages.error(request, 'Color inválido.')
            return redirect('/dashboard/landing/#settings')

        if action == 'basics_save':
            form = BasicsForm(request.POST, request.FILES, instance=professional)
            if form.is_valid():
                form.save()
                messages.success(request, 'Datos básicos actualizados.')
            else:
                messages.error(request, 'Revisá los campos.')
            return redirect('/dashboard/landing/#basics')

        if action == 'social_save':
            form = SocialLinksForm(request.POST, instance=professional)
            if form.is_valid():
                form.save()
                messages.success(request, 'Redes sociales actualizadas.')
            else:
                messages.error(request, 'Revisá las URLs — tienen que empezar con https://')
            return redirect('/dashboard/landing/#social')

        if action == 'testimonial_approve':
            obj = get_object_or_404(LandingTestimonial, id=request.POST.get('id'), professional=professional)
            obj.is_approved = True
            obj.save()
            messages.success(request, 'Reseña aprobada y publicada.')
            return redirect('/dashboard/landing/#testimonials')

        # Format: <section>_<verb> with verb in {add, save, delete}
        for section, (Model, FormCls, _) in LANDING_SECTIONS.items():
            anchor = f'/dashboard/landing/#{section}s'
            if action == f'{section}_add':
                instance = Model(professional=professional)
                form = FormCls(request.POST, request.FILES, instance=instance)
                if form.is_valid():
                    form.save()
                    messages.success(request, f'Item agregado.')
                else:
                    messages.error(request, 'No se pudo guardar. Revisá los campos.')
                return redirect(anchor)

            if action == f'{section}_save':
                obj = get_object_or_404(Model, id=request.POST.get('id'), professional=professional)
                form = FormCls(request.POST, request.FILES, instance=obj)
                if form.is_valid():
                    form.save()
                    messages.success(request, 'Cambios guardados.')
                return redirect(anchor)

            if action == f'{section}_delete':
                obj = get_object_or_404(Model, id=request.POST.get('id'), professional=professional)
                obj.delete()
                messages.success(request, 'Item eliminado.')
                return redirect(anchor)

    testimonials_qs = professional.landing_testimonials.all()
    return render(request, 'core/landing_admin.html', {
        'professional': professional,
        'stats': professional.landing_stats.all(),
        'credentials': professional.landing_credentials.all(),
        'services': professional.landing_services.all(),
        'testimonials': testimonials_qs.filter(is_approved=True),
        'pending_testimonials': testimonials_qs.filter(is_approved=False),
        'vertical_choices': VERTICAL_CHOICES,
        'public_url': request.build_absolute_uri(f'/p/{professional.slug}/'),
    })


# --- Public Landing & Booking ---

def public_landing(request, slug):
    professional = get_object_or_404(Professional, slug=slug)

    # Booking data for inline section
    selected_date_str = request.GET.get('date') or request.POST.get('date')
    working_day_nums = {DAYS_MAP[d] for d in professional.get_working_days_list() if d in DAYS_MAP}
    available_dates = []
    for i in range(1, 30):
        d = date.today() + timedelta(days=i)
        if d.weekday() in working_day_nums:
            available_dates.append(d)
        if len(available_dates) >= 14:
            break

    selected_date = None
    slots = []
    if selected_date_str:
        try:
            selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
            slots = get_available_slots(professional, selected_date)
        except ValueError:
            pass

    # Handle booking POST
    if request.method == 'POST' and 'first_name' in request.POST:
        form = BookingPatientForm(request.POST)
        selected_time_str = request.POST.get('time')
        if form.is_valid() and selected_date and selected_time_str:
            selected_time = datetime.strptime(selected_time_str, '%H:%M').time()
            if Appointment.objects.filter(
                professional=professional, appointment_date=selected_date,
                appointment_time=selected_time, status__in=['scheduled', 'confirmed']
            ).exists():
                messages.error(request, 'Este horario ya no está disponible.')
                return redirect('public_landing', slug=slug)

            data = form.cleaned_data

            if professional.both_modes:
                mode = data.get('mode') or 'presencial'
            elif professional.supports_online:
                mode = 'online'
            else:
                mode = 'presencial'

            selected_service = None
            service_id = data.get('service_id', '').strip()
            if service_id:
                selected_service = LandingService.objects.filter(
                    id=service_id, professional=professional, is_bookable=True
                ).first()

            patient, _ = Patient.objects.update_or_create(
                professional=professional, phone=data['phone'],
                defaults={
                    'first_name': data['first_name'], 'last_name': data['last_name'],
                    'email': data.get('email', ''),
                    'health_insurance': data.get('health_insurance', ''),
                    'health_insurance_plan': data.get('health_insurance_plan', ''),
                    'health_insurance_number': data.get('health_insurance_number', ''),
                }
            )
            appointment = Appointment.objects.create(
                professional=professional, patient=patient,
                appointment_date=selected_date, appointment_time=selected_time,
                reason=data.get('reason', ''), source='online',
                mode=mode,
                service=selected_service,
                price_at_booking=selected_service.price if selected_service else None,
            )
            send_appointment_confirmation(appointment, request=request)
            return render(request, 'core/booking_confirmation.html', {
                'professional': professional, 'date': selected_date, 'time': selected_time,
                'appointment': appointment,
            })

    form = BookingPatientForm()
    landing_services = professional.landing_services.all()
    return render(request, 'core/public_landing.html', {
        'professional': professional,
        'available_dates': available_dates,
        'selected_date': selected_date,
        'slots': slots,
        'form': form,
        'landing_stats': professional.landing_stats.all(),
        'landing_credentials': professional.landing_credentials.all(),
        'landing_services': landing_services,
        'bookable_services': [s for s in landing_services if s.is_bookable],
        'landing_testimonials': professional.landing_testimonials.filter(is_approved=True),
    })


def booking(request, slug):
    """Legacy redirect — booking is now inline in public_landing."""
    return redirect('public_landing', slug=slug)


def _appointment_datetime(appointment):
    """Naive datetime of the appointment slot. Matches the project's naive date/time fields."""
    return datetime.combine(appointment.appointment_date, appointment.appointment_time)


def _is_window_locked(appointment):
    """True if cancel/reschedule is blocked by the pro's anticipation policy or the turn already happened."""
    appt_dt = _appointment_datetime(appointment)
    now = datetime.now()
    if appt_dt < now:
        return True
    window_hours = appointment.professional.cancellation_window_hours
    if window_hours <= 0:
        return False
    return (appt_dt - now) < timedelta(hours=window_hours)


def _patient_appointment_context(appointment, token):
    can_act = (
        appointment.status not in ('cancelled', 'completed')
        and not _is_window_locked(appointment)
    )
    return {
        'appointment': appointment,
        'professional': appointment.professional,
        'patient': appointment.patient,
        'token': token,
        'can_act': can_act,
        'is_past': _appointment_datetime(appointment) < datetime.now(),
    }


def patient_appointment(request, token):
    appointment = parse_patient_token(token)
    if not appointment:
        return render(request, 'core/patient_link_expired.html', status=410)
    return render(request, 'core/patient_appointment.html', _patient_appointment_context(appointment, token))


@require_POST
def patient_cancel(request, token):
    appointment = parse_patient_token(token)
    if not appointment:
        return render(request, 'core/patient_link_expired.html', status=410)
    if appointment.status in ('cancelled', 'completed') or _is_window_locked(appointment):
        return redirect('patient_appointment', token=token)

    appointment.status = 'cancelled'
    appointment.save(update_fields=['status', 'updated_at'])
    send_cancellation_to_pro(appointment, request=request)
    return render(request, 'core/patient_cancelled.html', {
        'appointment': appointment,
        'professional': appointment.professional,
        'patient': appointment.patient,
    })


def patient_reschedule(request, token):
    appointment = parse_patient_token(token)
    if not appointment:
        return render(request, 'core/patient_link_expired.html', status=410)
    if appointment.status in ('cancelled', 'completed') or _is_window_locked(appointment):
        return redirect('patient_appointment', token=token)

    professional = appointment.professional
    working_day_nums = {DAYS_MAP[d] for d in professional.get_working_days_list() if d in DAYS_MAP}
    available_dates = []
    for i in range(1, 30):
        d = date.today() + timedelta(days=i)
        if d.weekday() in working_day_nums:
            available_dates.append(d)
        if len(available_dates) >= 14:
            break

    selected_date_str = request.GET.get('date') or request.POST.get('date')
    selected_date = None
    slots = []
    if selected_date_str:
        try:
            selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
            slots = get_available_slots(professional, selected_date)
        except ValueError:
            pass

    if request.method == 'POST' and request.POST.get('time'):
        try:
            new_time = datetime.strptime(request.POST['time'], '%H:%M').time()
        except ValueError:
            new_time = None

        if selected_date and new_time:
            taken = Appointment.objects.filter(
                professional=professional,
                appointment_date=selected_date,
                appointment_time=new_time,
                status__in=['scheduled', 'confirmed'],
            ).exclude(id=appointment.id).exists()

            if taken:
                messages.error(request, 'Ese horario acaba de ocuparse. Elegí otro.')
            else:
                old_date = appointment.appointment_date
                old_time = appointment.appointment_time
                appointment.appointment_date = selected_date
                appointment.appointment_time = new_time
                appointment.status = 'scheduled'
                appointment.save(update_fields=['appointment_date', 'appointment_time', 'status', 'updated_at'])
                send_reschedule_to_pro(appointment, old_date, old_time, request=request)
                send_appointment_confirmation(appointment, request=request)
                messages.success(request, 'Tu turno fue reagendado.')
                return redirect('patient_appointment', token=token)

    return render(request, 'core/patient_reschedule.html', {
        'appointment': appointment,
        'professional': professional,
        'patient': appointment.patient,
        'token': token,
        'available_dates': available_dates,
        'selected_date': selected_date,
        'slots': slots,
    })


def public_review(request, slug, token):
    professional = get_object_or_404(Professional, slug=slug)
    appointment = parse_review_token(token)

    if not appointment or appointment.professional_id != professional.id:
        return render(request, 'core/review.html', {
            'professional': professional, 'invalid': True,
        })

    if hasattr(appointment, 'testimonial'):
        return render(request, 'core/review.html', {
            'professional': professional, 'already_submitted': True,
        })

    if request.method == 'POST':
        form = PublicReviewForm(request.POST)
        if form.is_valid():
            patient = appointment.patient
            author_name = f'{patient.first_name} {patient.last_name[:1].upper()}.'
            LandingTestimonial.objects.create(
                professional=professional,
                appointment=appointment,
                quote=form.cleaned_data['quote'],
                rating=form.cleaned_data['rating'],
                author_name=author_name,
                author_meta=f'Paciente — {appointment.appointment_date.strftime("%m/%Y")}',
                is_approved=False,
            )
            return render(request, 'core/review.html', {
                'professional': professional, 'success': True,
            })
    else:
        form = PublicReviewForm()

    return render(request, 'core/review.html', {
        'professional': professional,
        'appointment': appointment,
        'form': form,
    })


# --- OG images (brand book v1.0 slides 21 + 23) ---

def _og_response(png_bytes, max_age):
    from django.http import HttpResponse
    response = HttpResponse(png_bytes, content_type='image/png')
    response['Cache-Control'] = f'public, max-age={max_age}'
    return response


def og_default(request):
    """Default OG image for the marketing site (1200×630)."""
    from .og import render_og_default
    return _og_response(render_og_default(), max_age=86400)


def og_professional(request, slug):
    """Per-professional OG image for /p/{slug} (1200×630)."""
    from .og import render_og_for_professional
    professional = get_object_or_404(Professional, slug=slug)
    return _og_response(render_og_for_professional(professional), max_age=3600)


# --- Clinic / Organization ---

def _get_owned_organization(request):
    """Return the Organization owned by the logged-in user, or None."""
    if not request.user.is_authenticated:
        return None
    return Organization.objects.filter(owner=request.user).first()


@login_required
def clinic_setup(request):
    """Convert a solo Professional account into a clinic (owner)."""
    professional = get_professional(request)
    if not professional:
        return redirect('setup')

    if _get_owned_organization(request):
        return redirect('clinic_dashboard')

    if request.method == 'POST':
        form = OrganizationSetupForm(request.POST)
        if form.is_valid():
            org = form.save(commit=False)
            org.owner = request.user
            org.save()
            professional.organization = org
            professional.role = 'owner'
            professional.save(update_fields=['organization', 'role'])
            messages.success(request, f'¡{org.name} creada! Ya podés invitar profesionales.')
            return redirect('clinic_dashboard')
    else:
        form = OrganizationSetupForm(initial={'name': '', 'phone': professional.phone,
                                              'address': professional.address,
                                              'email': professional.email})

    return render(request, 'core/clinic_setup.html', {
        'form': form,
        'professional': professional,
    })


@login_required
def clinic_dashboard(request):
    org = _get_owned_organization(request)
    if not org:
        return redirect('clinic_setup')

    members = list(org.members.select_related('user').all())
    pending_invites = list(org.invitations.filter(accepted_at__isnull=True).order_by('-created_at'))
    pending_invites = [inv for inv in pending_invites if not inv.is_expired]
    for inv in pending_invites:
        inv.join_url = request.build_absolute_uri(
            reverse('clinic_join', kwargs={'token': inv.token})
        )

    today = date.today()
    first_of_month = today.replace(day=1)
    member_ids = [m.id for m in members]
    appts_this_month = Appointment.objects.filter(
        professional_id__in=member_ids,
        appointment_date__gte=first_of_month,
        appointment_date__lte=today,
    ).count()
    upcoming = Appointment.objects.filter(
        professional_id__in=member_ids,
        appointment_date__gte=today,
    ).exclude(status='cancelled').count()

    return render(request, 'core/clinic_dashboard.html', {
        'organization': org,
        'members': members,
        'pending_invites': pending_invites,
        'kpi_members': len(members),
        'kpi_appts_this_month': appts_this_month,
        'kpi_upcoming': upcoming,
        'public_url': request.build_absolute_uri(reverse('clinic_public_landing', kwargs={'slug': org.slug})),
    })


@login_required
def clinic_invite(request):
    org = _get_owned_organization(request)
    if not org:
        return redirect('clinic_setup')

    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        already_member = org.members.filter(user__email__iexact=email).exists()
        already_invited = org.invitations.filter(email__iexact=email, accepted_at__isnull=True).exists()
        if already_member:
            messages.error(request, 'Esa persona ya es parte de la clínica.')
            return redirect('clinic_dashboard')
        if already_invited:
            messages.warning(request, 'Ya hay una invitación pendiente para ese email.')
            return redirect('clinic_dashboard')

        form = InvitationForm(request.POST)
        if form.is_valid():
            invitation = form.save(commit=False)
            invitation.organization = org
            invitation.invited_by = request.user
            invitation.save()
            send_clinic_invitation(invitation, request=request)
            messages.success(request, f'Invitación enviada a {invitation.email}.')
            return redirect('clinic_dashboard')
        messages.error(request, 'Revisá el email.')

    return redirect('clinic_dashboard')


@login_required
def clinic_revoke_invitation(request, invitation_id):
    org = _get_owned_organization(request)
    if not org:
        return redirect('clinic_setup')
    if request.method == 'POST':
        invitation = get_object_or_404(OrganizationInvitation, id=invitation_id, organization=org)
        invitation.delete()
        messages.success(request, 'Invitación cancelada.')
    return redirect('clinic_dashboard')


@login_required
def clinic_remove_member(request, professional_id):
    org = _get_owned_organization(request)
    if not org:
        return redirect('clinic_setup')
    if request.method == 'POST':
        member = get_object_or_404(Professional, id=professional_id, organization=org)
        if member.role == 'owner':
            messages.error(request, 'No podés sacarte a vos mismo de la clínica desde acá.')
            return redirect('clinic_dashboard')
        member.organization = None
        member.role = 'solo'
        member.save(update_fields=['organization', 'role'])
        messages.success(request, f'{member.professional_name} ya no pertenece a {org.name}.')
    return redirect('clinic_dashboard')


@login_required
def clinic_branding(request):
    org = _get_owned_organization(request)
    if not org:
        return redirect('clinic_setup')
    if request.method == 'POST':
        form = OrganizationBrandingForm(request.POST, request.FILES, instance=org)
        if form.is_valid():
            form.save()
            messages.success(request, 'Branding de la clínica actualizado.')
        else:
            messages.error(request, 'Revisá los campos.')
    return redirect('clinic_dashboard')


def clinic_join(request, token):
    """Public view: an invitee opens the magic link from their email."""
    invitation = get_object_or_404(OrganizationInvitation, token=token)
    if invitation.is_accepted:
        messages.info(request, 'Esta invitación ya fue aceptada.')
        return redirect('login')
    if invitation.is_expired:
        return render(request, 'core/clinic_join_expired.html', {'invitation': invitation}, status=410)

    if request.method == 'POST':
        form = JoinClinicForm(request.POST)
        errors = []
        if User.objects.filter(email__iexact=invitation.email).exists():
            errors.append('Ya existe una cuenta con ese email. Iniciá sesión y avisale al dueño de la clínica.')
        if form.is_valid() and not errors:
            user = User.objects.create_user(
                username=invitation.email,
                email=invitation.email,
                password=form.cleaned_data['password'],
            )
            org = invitation.organization
            professional = Professional.objects.create(
                user=user,
                organization=org,
                role='member',
                professional_name=form.cleaned_data['professional_name'],
                specialty=form.cleaned_data['specialty'],
                email=invitation.email,
                phone=form.cleaned_data.get('phone', '') or '',
                working_days='lunes,martes,miercoles,jueves,viernes',
                start_time='09:00',
                end_time='18:00',
                appointment_duration_minutes=30,
            )
            invitation.accepted_at = timezone.now()
            invitation.accepted_professional = professional
            invitation.save(update_fields=['accepted_at', 'accepted_professional'])
            login(request, user)
            messages.success(request, f'¡Bienvenido/a a {org.name}! Configurá tu agenda y tu landing.')
            return redirect('landing_admin')
        for field_errors in form.errors.values():
            errors.extend(field_errors)
        return render(request, 'core/clinic_join.html', {
            'invitation': invitation, 'form': form, 'errors': errors,
        })

    form = JoinClinicForm(initial={'professional_name': invitation.invited_name})
    return render(request, 'core/clinic_join.html', {
        'invitation': invitation, 'form': form,
    })


def clinic_public_landing(request, slug):
    """Public landing for a clinic, listing its professionals."""
    organization = get_object_or_404(Organization, slug=slug)
    members = organization.members.order_by('professional_name')
    return render(request, 'core/clinic_public_landing.html', {
        'organization': organization,
        'members': members,
    })


# --- Operator admin (superuser only) ---

def _superuser_required(view_func):
    from functools import wraps

    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_superuser:
            raise Http404()
        return view_func(request, *args, **kwargs)
    return wrapped


@_superuser_required
def operator_home(request):
    today = date.today()
    week_ago = today - timedelta(days=7)
    month_start = today.replace(day=1)
    days_30_ago = today - timedelta(days=30)

    users_total = User.objects.count()
    pros_total = Professional.objects.count()
    orgs_total = Organization.objects.count()

    appts_today = Appointment.objects.filter(appointment_date=today).count()
    appts_week = Appointment.objects.filter(appointment_date__gte=week_ago, appointment_date__lte=today).count()
    appts_month = Appointment.objects.filter(appointment_date__gte=month_start, appointment_date__lte=today).count()

    signups_week = User.objects.filter(date_joined__gte=week_ago).count()
    signups_today = User.objects.filter(date_joined__date=today).count()

    pro_subs = Subscription.objects.filter(plan='pro', status__in=['active', 'trialing']).count()
    free_subs = Subscription.objects.filter(plan='free').count()
    mrr_estimate_ars = pro_subs * 9900

    # Signups por día últimos 30
    signups_by_day = []
    for i in range(29, -1, -1):
        d = today - timedelta(days=i)
        c = User.objects.filter(date_joined__date=d).count()
        signups_by_day.append({'date': d, 'count': c})
    max_signups = max((s['count'] for s in signups_by_day), default=0) or 1

    pending_invites = OrganizationInvitation.objects.filter(accepted_at__isnull=True).count()
    pending_reviews = LandingTestimonial.objects.filter(is_approved=False).count()

    return render(request, 'core/operator/home.html', {
        'users_total': users_total,
        'pros_total': pros_total,
        'orgs_total': orgs_total,
        'appts_today': appts_today,
        'appts_week': appts_week,
        'appts_month': appts_month,
        'signups_today': signups_today,
        'signups_week': signups_week,
        'pro_subs': pro_subs,
        'free_subs': free_subs,
        'mrr_estimate_ars': mrr_estimate_ars,
        'signups_by_day': signups_by_day,
        'max_signups': max_signups,
        'pending_invites': pending_invites,
        'pending_reviews': pending_reviews,
    })


@_superuser_required
def operator_professionals(request):
    qs = Professional.objects.select_related('user', 'organization', 'user__subscription').order_by('-created_at')

    plan_filter = request.GET.get('plan', '')
    vertical_filter = request.GET.get('vertical', '')
    clinic_filter = request.GET.get('clinic', '')
    search = request.GET.get('q', '').strip()

    if plan_filter in ('free', 'pro'):
        qs = qs.filter(user__subscription__plan=plan_filter)
    if vertical_filter:
        qs = qs.filter(vertical=vertical_filter)
    if clinic_filter == 'yes':
        qs = qs.filter(organization__isnull=False)
    elif clinic_filter == 'no':
        qs = qs.filter(organization__isnull=True)
    if search:
        qs = qs.filter(
            Q(professional_name__icontains=search) |
            Q(email__icontains=search) |
            Q(specialty__icontains=search)
        )

    month_start = date.today().replace(day=1)
    pros = list(qs[:200])
    pro_ids = [p.id for p in pros]
    appt_counts = dict(
        Appointment.objects.filter(professional_id__in=pro_ids,
                                   appointment_date__gte=month_start)
        .values('professional_id')
        .annotate(c=Count('id'))
        .values_list('professional_id', 'c')
    )
    for p in pros:
        p._appt_month = appt_counts.get(p.id, 0)

    from .models import VERTICAL_CHOICES
    return render(request, 'core/operator/professionals.html', {
        'pros': pros,
        'total': qs.count(),
        'plan_filter': plan_filter,
        'vertical_filter': vertical_filter,
        'clinic_filter': clinic_filter,
        'search': search,
        'vertical_choices': VERTICAL_CHOICES,
    })


@_superuser_required
def operator_organizations(request):
    orgs = Organization.objects.select_related('owner').annotate(
        member_count=Count('members'),
    ).order_by('-created_at')

    month_start = date.today().replace(day=1)
    out = []
    for org in orgs:
        member_ids = list(org.members.values_list('id', flat=True))
        appts_month = Appointment.objects.filter(
            professional_id__in=member_ids,
            appointment_date__gte=month_start,
        ).count() if member_ids else 0
        out.append({'org': org, 'appts_month': appts_month})

    return render(request, 'core/operator/organizations.html', {
        'rows': out,
        'total': orgs.count(),
    })


@_superuser_required
def operator_appointments(request):
    appts = (Appointment.objects
             .select_related('professional', 'patient', 'service')
             .order_by('-created_at')[:100])
    return render(request, 'core/operator/appointments.html', {
        'appointments': appts,
    })


@_superuser_required
def operator_user_detail(request, user_id):
    user = get_object_or_404(User.objects.select_related('subscription'), id=user_id)
    professional = getattr(user, 'professional', None)
    owned_org = Organization.objects.filter(owner=user).first()
    appts_total = Appointment.objects.filter(professional=professional).count() if professional else 0
    month_start = date.today().replace(day=1)
    appts_month = (Appointment.objects.filter(professional=professional, appointment_date__gte=month_start).count()
                   if professional else 0)
    last_appts = (Appointment.objects.filter(professional=professional)
                  .select_related('patient').order_by('-created_at')[:10]
                  if professional else [])
    return render(request, 'core/operator/user_detail.html', {
        'detail_user': user,
        'professional': professional,
        'owned_organization': owned_org,
        'appts_total': appts_total,
        'appts_month': appts_month,
        'last_appts': last_appts,
    })


@_superuser_required
def operator_toggle_pro(request, user_id):
    if request.method != 'POST':
        return redirect('operator_user_detail', user_id=user_id)
    user = get_object_or_404(User, id=user_id)
    sub, _ = Subscription.objects.get_or_create(user=user, defaults={'plan': 'free'})
    if sub.plan == 'pro':
        sub.plan = 'free'
        sub.status = 'active'
        sub.cancelled_at = timezone.now()
        sub.manually_set = True
        messages.success(request, f'{user.email} pasó a Free.')
    else:
        sub.plan = 'pro'
        sub.status = 'active'
        sub.cancelled_at = None
        sub.manually_set = True
        messages.success(request, f'{user.email} activado en Pro manualmente.')
    sub.save()
    return redirect('operator_user_detail', user_id=user_id)
