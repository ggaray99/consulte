import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

HEX_COLOR_VALIDATOR = RegexValidator(r'^#(?:[0-9a-fA-F]{3}){1,2}$', 'Color en formato hex. Ej: #0047ab')


# Brand book v1.0 — verticales opt-in y sus tints
VERTICAL_CHOICES = [
    ('salud',     'Salud'),
    ('legal',     'Legal'),
    ('contable',  'Contable / financiero'),
    ('coaching',  'Coaching / consultoría'),
    ('creativos', 'Servicios creativos y técnicos'),
    ('bienestar', 'Bienestar'),
]

VERTICAL_TINTS = {
    'salud':     '#5BB89A',   # Mint sereno
    'legal':     '#3D4F8F',   # Indigo profundo
    'contable':  '#8C7344',   # Bronce mate
    'coaching':  '#D88061',   # Coral cálido
    'creativos': '#7D5E94',   # Plum editorial
    'bienestar': '#8A9F7E',   # Sage tierra
}

CURRENCY_CHOICES = [
    ('ARS', 'ARS — Pesos argentinos'),
    ('USD', 'USD — Dólares'),
]


class Organization(models.Model):
    """Clínica o consultora con uno o más profesionales adentro."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name='owned_organizations')
    name = models.CharField('Nombre de la clínica/consultora', max_length=255)
    slug = models.SlugField(unique=True, max_length=255)
    tagline = models.CharField('Frase de valor', max_length=255, blank=True)
    bio = models.TextField('Descripción', blank=True)
    mission = models.TextField('Misión', blank=True)
    address = models.CharField('Dirección', max_length=255, blank=True)
    phone = models.CharField('Teléfono', max_length=50, blank=True)
    email = models.EmailField('Email de contacto', blank=True)
    logo = models.ImageField('Logo', upload_to='organizations/', blank=True, null=True)
    theme_primary = models.CharField('Color principal', max_length=7, default='#0047ab',
                                     validators=[HEX_COLOR_VALIDATOR])
    instagram_url = models.URLField('Instagram', blank=True, default='')
    facebook_url = models.URLField('Facebook', blank=True, default='')
    x_url = models.URLField('X (Twitter)', blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Clínica / Consultora'
        verbose_name_plural = 'Clínicas / Consultoras'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 2
            while Organization.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base_slug}-{counter}'
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def has_social_links(self):
        return bool(self.instagram_url or self.facebook_url or self.x_url)


class OrganizationInvitation(models.Model):
    """Invitación pendiente para que un profesional se sume a una clínica."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE,
                                     related_name='invitations')
    email = models.EmailField('Email del invitado')
    invited_name = models.CharField('Nombre', max_length=255, blank=True,
                                    help_text='Opcional. Se usa solo para el saludo en el email.')
    token = models.CharField(max_length=64, unique=True, editable=False)
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='sent_invitations')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_professional = models.ForeignKey('Professional', on_delete=models.SET_NULL,
                                              null=True, blank=True,
                                              related_name='+',
                                              help_text='Profesional creado al aceptar la invitación.')

    class Meta:
        verbose_name = 'Invitación a clínica'
        verbose_name_plural = 'Invitaciones a clínica'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.email} → {self.organization.name}'

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(32)
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(days=14)
        super().save(*args, **kwargs)

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def is_accepted(self):
        return self.accepted_at is not None

    @property
    def is_pending(self):
        return not self.is_accepted and not self.is_expired


class Professional(models.Model):
    ROLE_CHOICES = [
        ('solo',   'Profesional individual'),
        ('owner',  'Dueño/a de clínica'),
        ('member', 'Miembro de clínica'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='professional', null=True)
    organization = models.ForeignKey(Organization, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name='members',
                                     help_text='Si pertenece a una clínica/consultora, su organización. Null = profesional independiente.')
    role = models.CharField('Rol', max_length=20, choices=ROLE_CHOICES, default='solo',
                            help_text='solo = sin clínica; owner = dueño; member = profesional invitado.')
    professional_name = models.CharField('Nombre completo', max_length=255)
    specialty = models.CharField('Especialidad', max_length=255)
    vertical = models.CharField('Vertical', max_length=20, choices=VERTICAL_CHOICES, blank=True, default='',
                                help_text='Categoría de servicio. Si se selecciona, define el tint de acento de la landing y la OG image.')
    email = models.EmailField('Email', unique=True)
    phone = models.CharField('Teléfono', max_length=50, blank=True)
    address = models.CharField('Dirección', max_length=255, blank=True)
    bio = models.TextField('Descripción profesional', blank=True)
    tagline = models.CharField('Frase de valor', max_length=255, blank=True)
    attention_mode = models.CharField('Modalidad de atención', max_length=100, blank=True, help_text='Ej: Presencial, Online, Presencial y online')
    accepts_insurance = models.BooleanField('Acepta obra social', default=False)
    accepts_private = models.BooleanField('Acepta particular', default=True)
    profile_image = models.ImageField('Foto de perfil', upload_to='professionals/', blank=True, null=True)
    hero_image = models.ImageField('Imagen de portada', upload_to='professionals/heroes/', blank=True, null=True,
                                   help_text='Imagen full-screen del hero. Recomendado paisaje 1920×1080. Si la dejás vacía, se usa el layout de tarjeta clásico con la foto de perfil.')
    common_reasons = models.TextField('Motivos frecuentes de consulta', blank=True, help_text='Separados por coma. Ej: Ansiedad, Estrés, Autoestima')
    mission = models.TextField('Misión / Filosofía', blank=True, help_text='Frase destacada que aparece en la landing como tarjeta azul.')
    theme_primary = models.CharField('Color principal', max_length=7, default='#0047ab', validators=[HEX_COLOR_VALIDATOR],
                                     help_text='Color de CTAs, links y tarjeta de misión. Si dejás vertical seleccionada y este campo en cobalto (#0047ab), el accent toma el tint del vertical.')
    show_stats = models.BooleanField('Mostrar estadísticas', default=True)
    show_credentials = models.BooleanField('Mostrar credenciales', default=True)
    show_mission = models.BooleanField('Mostrar misión', default=True)
    show_services = models.BooleanField('Mostrar servicios', default=True)
    show_testimonials = models.BooleanField('Mostrar testimonios', default=True)
    show_contact = models.BooleanField('Mostrar sección de contacto', default=True)
    show_map = models.BooleanField('Mostrar mapa de ubicación', default=True,
                                   help_text='Solo se renderiza si además hay una dirección cargada.')
    currency = models.CharField('Moneda', max_length=3, choices=CURRENCY_CHOICES, default='ARS',
                                help_text='Moneda en la que mostrás los precios de tus servicios.')
    instagram_url = models.URLField('Instagram', blank=True, default='',
                                    help_text='URL completa de tu perfil. Ej: https://instagram.com/tu-usuario')
    facebook_url = models.URLField('Facebook', blank=True, default='',
                                   help_text='URL completa de tu página o perfil.')
    x_url = models.URLField('X (Twitter)', blank=True, default='',
                            help_text='URL completa de tu perfil. Ej: https://x.com/tu-usuario')
    slug = models.SlugField(unique=True, max_length=255)
    working_days = models.CharField('Días de atención', max_length=255, help_text='Ej: lunes,martes,miercoles')
    start_time = models.TimeField('Hora de inicio')
    end_time = models.TimeField('Hora de fin')
    appointment_duration_minutes = models.IntegerField('Duración del turno (min)', default=30)
    cancellation_window_hours = models.PositiveIntegerField(
        'Anticipación mínima para cancelar/reagendar (horas)',
        default=24,
        help_text='El paciente puede cancelar o reagendar desde el link en su email hasta esta cantidad de horas antes del turno. 0 = sin restricción.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Profesional'
        verbose_name_plural = 'Profesionales'

    def __str__(self):
        return f'{self.professional_name} - {self.specialty}'

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.professional_name)
            slug = base_slug
            counter = 2
            while Professional.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base_slug}-{counter}'
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def get_working_days_list(self):
        return [d.strip().lower() for d in self.working_days.split(',') if d.strip()]

    def get_common_reasons_list(self):
        if not self.common_reasons:
            return []
        return [r.strip() for r in self.common_reasons.split(',') if r.strip()]

    @property
    def vertical_tint(self):
        """Hex del tint correspondiente a la vertical, o None si no hay vertical."""
        return VERTICAL_TINTS.get(self.vertical) if self.vertical else None

    @property
    def supports_online(self):
        """True if the pro's attention_mode mentions 'online'."""
        return 'online' in (self.attention_mode or '').lower()

    @property
    def supports_presencial(self):
        """True if the pro accepts in-person (or hasn't configured the field)."""
        attention = (self.attention_mode or '').lower()
        return 'presencial' in attention or not attention

    @property
    def both_modes(self):
        """True when the pro accepts both formats and the patient must choose."""
        return self.supports_online and self.supports_presencial

    @property
    def has_social_links(self):
        return bool(self.instagram_url or self.facebook_url or self.x_url)

    @property
    def accent_color(self):
        """Color de acento para la landing pública.

        El tint del vertical gana cuando está definido y el profesional dejó
        theme_primary en el default (#0047ab). Si customizó theme_primary,
        ese tiene prioridad. Si no hay vertical, cae a theme_primary.
        """
        if self.vertical_tint and (self.theme_primary or '').lower() == '#0047ab':
            return self.vertical_tint
        return self.theme_primary or '#0047ab'


class Patient(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    professional = models.ForeignKey(Professional, on_delete=models.CASCADE, related_name='patients')
    first_name = models.CharField('Nombre', max_length=255)
    last_name = models.CharField('Apellido', max_length=255)
    phone = models.CharField('Teléfono', max_length=50)
    email = models.EmailField('Email', blank=True)
    address = models.CharField('Dirección', max_length=255, blank=True)
    health_insurance = models.CharField('Obra social', max_length=255, blank=True)
    health_insurance_plan = models.CharField('Plan', max_length=255, blank=True)
    health_insurance_number = models.CharField('Nro. afiliado', max_length=255, blank=True)
    clinical_notes = models.TextField('Notas clínicas', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Paciente'
        verbose_name_plural = 'Pacientes'
        unique_together = ['professional', 'phone']

    def __str__(self):
        return f'{self.first_name} {self.last_name}'


class LandingStat(models.Model):
    professional = models.ForeignKey(Professional, on_delete=models.CASCADE, related_name='landing_stats')
    value = models.CharField('Valor', max_length=50, help_text='Ej: 15+, 10k+, 4.9, 24')
    label = models.CharField('Etiqueta', max_length=100, help_text='Ej: Años de experiencia')
    order = models.PositiveIntegerField('Orden', default=0)

    class Meta:
        ordering = ['order']
        verbose_name = 'Estadística de landing'
        verbose_name_plural = 'Landing — Estadísticas'

    def __str__(self):
        return f'{self.value} {self.label}'


class LandingCredential(models.Model):
    professional = models.ForeignKey(Professional, on_delete=models.CASCADE, related_name='landing_credentials')
    icon = models.CharField('Icono Material', max_length=50, default='workspace_premium',
                            help_text='Nombre de Material Symbol. Ej: school, workspace_premium, clinical_notes, verified')
    title = models.CharField('Título', max_length=200)
    subtitle = models.CharField('Institución / detalle', max_length=255, blank=True)
    order = models.PositiveIntegerField('Orden', default=0)

    class Meta:
        ordering = ['order']
        verbose_name = 'Credencial'
        verbose_name_plural = 'Landing — Credenciales'

    def __str__(self):
        return self.title


class LandingService(models.Model):
    professional = models.ForeignKey(Professional, on_delete=models.CASCADE, related_name='landing_services')
    icon = models.CharField('Icono Material', max_length=50, default='medical_services',
                            help_text='Nombre de Material Symbol. Se usa cuando no cargás imagen. Ej: monitor_heart, content_cut, fitness_center, brush.')
    image = models.ImageField('Imagen', upload_to='landing_services/', blank=True, null=True,
                              help_text='Foto del servicio (cuadrada o vertical, 800×800 o similar). Si la cargás, reemplaza el icono en la landing pública.')
    title = models.CharField('Título', max_length=100)
    description = models.TextField('Descripción')
    price = models.DecimalField('Precio', max_digits=10, decimal_places=2, null=True, blank=True,
                                help_text='Opcional. Si lo dejás vacío, no se muestra precio en la landing.')
    is_bookable = models.BooleanField('Reservable online', default=True,
                                      help_text='Si está activo, los pacientes pueden elegir este servicio al reservar. Desactivá para servicios solo informativos (charlas, workshops).')
    order = models.PositiveIntegerField('Orden', default=0)

    class Meta:
        ordering = ['order']
        verbose_name = 'Servicio'
        verbose_name_plural = 'Landing — Servicios'

    def __str__(self):
        return self.title

    @property
    def formatted_price(self):
        """Returns the price formatted for display, or '' if no price set.

        ARS uses dot for thousands and comma for decimals (Argentine convention):
        '$ 15.000' or '$ 1.500,50'. USD uses comma for thousands and dot for
        decimals: 'USD 1,200' or 'USD 25.50'.
        """
        if self.price is None:
            return ''
        currency = (self.professional.currency or 'ARS').upper()
        is_whole = self.price == self.price.to_integral_value()
        if currency == 'USD':
            return f'USD {int(self.price):,}' if is_whole else f'USD {self.price:,.2f}'
        # ARS: swap , and . (Python defaults to anglo format)
        if is_whole:
            return f'$ {int(self.price):,}'.replace(',', '.')
        anglo = f'{self.price:,.2f}'  # e.g. '1,500.50'
        return f'$ {anglo.replace(",", "X").replace(".", ",").replace("X", ".")}'


class LandingTestimonial(models.Model):
    professional = models.ForeignKey(Professional, on_delete=models.CASCADE, related_name='landing_testimonials')
    appointment = models.OneToOneField('Appointment', on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='testimonial',
                                       help_text='Si vino del flujo post-turno, queda atado al turno (1 reseña por turno).')
    quote = models.TextField('Texto del testimonio')
    author_name = models.CharField('Nombre del autor', max_length=100)
    author_meta = models.CharField('Detalle', max_length=100, blank=True, help_text='Ej: Paciente desde 2021')
    rating = models.PositiveSmallIntegerField('Estrellas (0-5)', default=5)
    is_approved = models.BooleanField('Aprobado', default=True,
                                      help_text='Las reseñas creadas vía link público arrancan en False hasta que el profesional las aprueba.')
    order = models.PositiveIntegerField('Orden', default=0)
    created_at = models.DateTimeField(auto_now_add=True, null=True)

    class Meta:
        ordering = ['order', '-created_at']
        verbose_name = 'Testimonio'
        verbose_name_plural = 'Landing — Testimonios'

    def __str__(self):
        return f'{self.author_name} — {self.quote[:40]}'


class Appointment(models.Model):
    STATUS_CHOICES = [
        ('scheduled', 'Agendado'),
        ('confirmed', 'Confirmado'),
        ('cancelled', 'Cancelado'),
        ('completed', 'Completado'),
    ]
    SOURCE_CHOICES = [
        ('online', 'Online'),
        ('manual', 'Manual'),
        ('whatsapp', 'WhatsApp'),
        ('email', 'Email'),
        ('phone', 'Teléfono'),
    ]
    MODE_CHOICES = [
        ('presencial', 'Presencial'),
        ('online',     'Online (videollamada)'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    professional = models.ForeignKey(Professional, on_delete=models.CASCADE, related_name='appointments')
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='appointments')
    appointment_date = models.DateField('Fecha')
    appointment_time = models.TimeField('Hora')
    reason = models.TextField('Motivo', blank=True)
    status = models.CharField('Estado', max_length=50, choices=STATUS_CHOICES, default='scheduled')
    source = models.CharField('Origen', max_length=50, choices=SOURCE_CHOICES, default='online')
    mode = models.CharField('Modalidad', max_length=20, choices=MODE_CHOICES, default='presencial',
                            help_text='Presencial o videollamada. Si es online, se genera un link de Jitsi automáticamente.')
    meeting_url = models.URLField('Link de videollamada', blank=True, default='',
                                  help_text='Solo se completa cuando el turno es online.')
    notes = models.TextField('Notas del turno', blank=True, default='',
                             help_text='Notas privadas del profesional sobre este turno. Solo vos las ves.')
    service = models.ForeignKey('LandingService', on_delete=models.SET_NULL, null=True, blank=True,
                                related_name='appointments',
                                help_text='Servicio elegido. Si es null, se trata como consulta general.')
    price_at_booking = models.DecimalField('Precio al reservar', max_digits=10, decimal_places=2,
                                            null=True, blank=True,
                                            help_text='Precio congelado al momento de la reserva, independiente de cambios posteriores en el servicio.')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Turno'
        verbose_name_plural = 'Turnos'
        unique_together = ['professional', 'appointment_date', 'appointment_time']
        ordering = ['appointment_date', 'appointment_time']

    def __str__(self):
        return f'{self.patient} - {self.appointment_date} {self.appointment_time}'

    def generate_meeting_url(self):
        """Returns a deterministic Jitsi room URL derived from this appointment's UUID.

        Same appointment always resolves to the same room, so the patient and the
        professional join the same call without coordinating room names.
        """
        room = f"consulte-{str(self.id).split('-')[0]}"
        return f"https://meet.jit.si/{room}"

    def save(self, *args, **kwargs):
        # uuid is assigned at __init__ (default=uuid.uuid4), so self.id is
        # always available here — no need for a two-step save.
        if self.mode == 'online' and not self.meeting_url:
            self.meeting_url = self.generate_meeting_url()
        super().save(*args, **kwargs)


class Subscription(models.Model):
    """Plan + estado de cobro del usuario. Se crea auto en signup como 'free'."""
    PLAN_CHOICES = [
        ('free', 'Free'),
        ('pro',  'Pro'),
    ]
    STATUS_CHOICES = [
        ('active',    'Activa'),
        ('trialing',  'En prueba'),
        ('past_due',  'Pago vencido'),
        ('cancelled', 'Cancelada'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name='subscription')
    plan = models.CharField(max_length=10, choices=PLAN_CHOICES, default='free')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    mp_preapproval_id = models.CharField('Mercado Pago preapproval ID', max_length=100,
                                         blank=True, default='')
    trial_end = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    manually_set = models.BooleanField(default=False,
                                       help_text='True cuando el plan fue cambiado a mano desde el admin de operador. Bloquea sobrescritura por webhooks de MP.')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Suscripción'
        verbose_name_plural = 'Suscripciones'

    def __str__(self):
        return f'{self.user.email} — {self.get_plan_display()} ({self.get_status_display()})'

    @property
    def is_pro(self):
        """True si el plan da acceso a features Pro (independiente del proveedor de cobro)."""
        if self.plan != 'pro':
            return False
        return self.status in ('active', 'trialing')
