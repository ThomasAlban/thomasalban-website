from django.db import migrations, models
from django.db.migrations.exceptions import IrreversibleError


def copy_categories(apps, schema_editor):
    Composition = apps.get_model('compositions', 'Composition')
    Category = apps.get_model('compositions', 'Category')
    database = schema_editor.connection.alias
    for composition in Composition.objects.using(database).exclude(category='').iterator():
        category, _ = Category.objects.using(database).get_or_create(name=composition.category)
        composition.categories.add(category)


def restore_categories(apps, schema_editor):
    Composition = apps.get_model('compositions', 'Composition')
    database = schema_editor.connection.alias
    compositions = Composition.objects.using(database).prefetch_related('categories')
    # Refuse a rollback that would silently discard additional categories.
    if any(len(composition.categories.all()) > 1 for composition in compositions):
        raise IrreversibleError('Remove extra categories before reverting to a single category.')
    for composition in compositions:
        categories = list(composition.categories.all())
        Composition.objects.using(database).filter(pk=composition.pk).update(
            category=categories[0].name if categories else '',
        )


class Migration(migrations.Migration):
    dependencies = [
        ('compositions', '0009_composition_updated_at'),
    ]

    operations = [
        migrations.CreateModel(
            name='Category',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True)),
            ],
            options={'ordering': ['name'], 'verbose_name_plural': 'categories'},
        ),
        migrations.AddField(
            model_name='composition',
            name='categories',
            field=models.ManyToManyField(blank=True, related_name='compositions', to='compositions.category'),
        ),
        migrations.RunPython(copy_categories, restore_categories),
        migrations.RemoveField(model_name='composition', name='category'),
    ]
