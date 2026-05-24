from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0016_backfill_subscriptions'),
    ]

    operations = [
        migrations.AddField(
            model_name='professional',
            name='cancellation_window_hours',
            field=models.PositiveIntegerField(
                default=24,
                help_text='El paciente puede cancelar o reagendar desde el link en su email hasta esta cantidad de horas antes del turno. 0 = sin restricción.',
                verbose_name='Anticipación mínima para cancelar/reagendar (horas)',
            ),
        ),
    ]
