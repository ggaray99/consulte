# consulte.

Plataforma para que profesionales independientes (salud, legal, contable, coaching, consultoría, creativos) creen su landing pública y gestionen turnos online. Django 6 + Tailwind (CDN). Dominio: `consulte.app`.

## Desarrollo local

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

App en `http://127.0.0.1:8000/`. Admin en `/admin/`.

## Variables de entorno

Localmente todas tienen defaults sensatos. En producción setear:

| Variable | Para qué |
|---|---|
| `SECRET_KEY` | Clave secreta de Django (generar una nueva) |
| `DEBUG` | `False` en prod |
| `ALLOWED_HOSTS` | Hosts permitidos, separados por coma |
| `CSRF_TRUSTED_ORIGINS` | URLs HTTPS confiables, separadas por coma |
| `DATABASE_URL` | URL de Postgres (autodetectada en Railway) |
| `MEDIA_ROOT` | Ruta para uploads (en Railway, montar Volume) |

## Estructura

- `core/` — app principal: `Professional`, `Patient`, `Appointment` + 4 modelos repeater para landing
- `consulte/` — config Django (urls, settings, wsgi)
- `templates/core/` — templates: dashboard, landing pública, admin de landing, etc.
- `diseñostich/` — referencia de diseño Stitch ("Clinical Clarity") usada para el landing público

## Deploy en Railway

1. Push a GitHub
2. Crear proyecto en railway.app desde el repo
3. Agregar plugin de **PostgreSQL**
4. Agregar **Volume** montado en `/app/media` para uploads persistentes
5. Setear env vars listadas arriba
6. Deploy se hace automático en cada push a `main`
