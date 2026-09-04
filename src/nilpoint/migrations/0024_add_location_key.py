from django.db import migrations
import uuid

def generate_unique_tokens(apps, schema_editor):
    Location = apps.get_model('nilpoint', 'Location')
    
    # Loop through each row and save a uniquely generated string
    for row in Location.objects.filter(np_key__isnull=True):
        row.np_key = str(uuid.uuid4()) # Or your own unique generation logic
        row.save()

class Migration(migrations.Migration):

    dependencies = [
        ('nilpoint', '0023_location_np_key'),
    ]

    operations = [
        migrations.RunPython(generate_unique_tokens),
    ]
