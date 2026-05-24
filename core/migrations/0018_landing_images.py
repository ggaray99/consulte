from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0017_professional_cancellation_window_hours'),
    ]

    operations = [
        migrations.AddField(
            model_name='professional',
            name='hero_image',
            field=models.ImageField(
                blank=True, null=True,
                upload_to='professionals/heroes/',
                verbose_name='Imagen de portada',
                help_text='Imagen full-screen del hero. Recomendado paisaje 1920×1080. Si la dejás vacía, se usa el layout de tarjeta clásico con la foto de perfil.',
            ),
        ),
        migrations.AddField(
            model_name='landingservice',
            name='image',
            field=models.ImageField(
                blank=True, null=True,
                upload_to='landing_services/',
                verbose_name='Imagen',
                help_text='Foto del servicio (cuadrada o vertical, 800×800 o similar). Si la cargás, reemplaza el icono en la landing pública.',
            ),
        ),
        migrations.AlterField(
            model_name='landingservice',
            name='icon',
            field=models.CharField(
                default='medical_services',
                max_length=50,
                verbose_name='Icono Material',
                help_text='Nombre de Material Symbol. Se usa cuando no cargás imagen. Ej: monitor_heart, content_cut, fitness_center, brush.',
            ),
        ),
    ]
