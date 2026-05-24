from django import forms
from .models import (
    Professional, Patient, Appointment, Organization, OrganizationInvitation,
    LandingStat, LandingCredential, LandingService, LandingTestimonial,
)


class ProfessionalSetupForm(forms.ModelForm):
    class Meta:
        model = Professional
        fields = ['professional_name', 'specialty', 'vertical', 'email', 'phone', 'address', 'bio',
                  'tagline', 'attention_mode', 'accepts_insurance', 'accepts_private',
                  'profile_image', 'common_reasons',
                  'working_days', 'start_time', 'end_time', 'appointment_duration_minutes']


class PatientForm(forms.ModelForm):
    class Meta:
        model = Patient
        fields = ['first_name', 'last_name', 'phone', 'email', 'address',
                  'health_insurance', 'health_insurance_plan', 'health_insurance_number']


class BookingPatientForm(forms.Form):
    MODE_CHOICES = [
        ('presencial', 'Presencial'),
        ('online',     'Videollamada'),
    ]

    first_name = forms.CharField(max_length=255, label='Nombre')
    last_name = forms.CharField(max_length=255, label='Apellido')
    phone = forms.CharField(max_length=50, label='Teléfono')
    email = forms.EmailField(required=False, label='Email')
    health_insurance = forms.CharField(max_length=255, required=False, label='Obra social')
    health_insurance_plan = forms.CharField(max_length=255, required=False, label='Plan')
    health_insurance_number = forms.CharField(max_length=255, required=False, label='Nro. afiliado')
    reason = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}), required=False, label='Motivo de consulta')
    mode = forms.ChoiceField(choices=MODE_CHOICES, required=False,
                              widget=forms.RadioSelect, label='Modalidad')
    service_id = forms.CharField(required=False, widget=forms.HiddenInput)


class ManualAppointmentForm(forms.Form):
    patient_search = forms.CharField(max_length=255, required=False, label='Buscar paciente')
    first_name = forms.CharField(max_length=255, required=False, label='Nombre')
    last_name = forms.CharField(max_length=255, required=False, label='Apellido')
    phone = forms.CharField(max_length=50, required=False, label='Teléfono')
    email = forms.EmailField(required=False, label='Email')
    appointment_date = forms.DateField(label='Fecha')
    appointment_time = forms.TimeField(label='Hora')
    reason = forms.CharField(widget=forms.Textarea(attrs={'rows': 2}), required=False, label='Motivo')
    status = forms.ChoiceField(choices=Appointment.STATUS_CHOICES, initial='scheduled', label='Estado')


class ClinicalNotesForm(forms.Form):
    clinical_notes = forms.CharField(widget=forms.Textarea(attrs={'rows': 6}), required=False, label='Notas clínicas')


class MissionForm(forms.ModelForm):
    class Meta:
        model = Professional
        fields = ['mission']


class LandingSettingsForm(forms.ModelForm):
    class Meta:
        model = Professional
        fields = ['vertical', 'theme_primary', 'currency',
                  'show_stats', 'show_credentials', 'show_mission',
                  'show_services', 'show_testimonials', 'show_contact', 'show_map']


class BasicsForm(forms.ModelForm):
    class Meta:
        model = Professional
        fields = ['professional_name', 'specialty', 'tagline', 'bio', 'profile_image', 'hero_image',
                  'cancellation_window_hours']


class SocialLinksForm(forms.ModelForm):
    class Meta:
        model = Professional
        fields = ['instagram_url', 'facebook_url', 'x_url']


class LandingStatForm(forms.ModelForm):
    class Meta:
        model = LandingStat
        fields = ['value', 'label', 'order']


class LandingCredentialForm(forms.ModelForm):
    class Meta:
        model = LandingCredential
        fields = ['icon', 'title', 'subtitle', 'order']


class LandingServiceForm(forms.ModelForm):
    class Meta:
        model = LandingService
        fields = ['icon', 'image', 'title', 'description', 'price', 'is_bookable', 'order']


class LandingTestimonialForm(forms.ModelForm):
    class Meta:
        model = LandingTestimonial
        fields = ['quote', 'author_name', 'author_meta', 'rating', 'order']


class PublicReviewForm(forms.Form):
    rating = forms.IntegerField(min_value=1, max_value=5, label='Puntaje')
    quote = forms.CharField(widget=forms.Textarea(attrs={'rows': 4, 'maxlength': 600}),
                            label='¿Cómo fue tu experiencia?', max_length=600)


class OrganizationSetupForm(forms.ModelForm):
    """Form para convertir una cuenta solo en cuenta de clínica."""
    class Meta:
        model = Organization
        fields = ['name', 'tagline', 'address', 'phone', 'email']


class OrganizationBrandingForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ['name', 'tagline', 'bio', 'mission', 'address', 'phone', 'email',
                  'logo', 'theme_primary', 'instagram_url', 'facebook_url', 'x_url']


class InvitationForm(forms.ModelForm):
    class Meta:
        model = OrganizationInvitation
        fields = ['email', 'invited_name']


class JoinClinicForm(forms.Form):
    """Form que ve un invitado al aceptar la invitación. Crea User + Professional."""
    professional_name = forms.CharField(max_length=255, label='Tu nombre completo')
    specialty = forms.CharField(max_length=255, label='Especialidad')
    phone = forms.CharField(max_length=50, required=False, label='Teléfono (opcional)')
    password = forms.CharField(widget=forms.PasswordInput, min_length=8, label='Contraseña',
                               help_text='Mínimo 8 caracteres.')
