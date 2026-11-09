from django.db import migrations, models
import django.db.models.deletion


def copy_memberships(apps, schema_editor):
    Composition = apps.get_model('compositions', 'Composition')
    Membership = apps.get_model('compositions', 'CompositionCategory')
    database = schema_editor.connection.alias
    for composition in Composition.objects.using(database).iterator():
        Membership.objects.using(database).bulk_create([
            Membership(composition_id=composition.pk, category_id=category.pk, position=position)
            for position, category in enumerate(composition.categories.using(database).order_by('name', 'pk'))
        ])


def restore_memberships(apps, schema_editor):
    Composition = apps.get_model('compositions', 'Composition')
    Membership = apps.get_model('compositions', 'CompositionCategory')
    database = schema_editor.connection.alias
    Through = Composition.categories.through
    Through.objects.using(database).bulk_create([
        Through(composition_id=membership.composition_id, category_id=membership.category_id)
        for membership in Membership.objects.using(database).iterator()
    ])


class Migration(migrations.Migration):
    dependencies = [
        ('compositions', '0010_composition_categories'),
    ]

    operations = [
        migrations.CreateModel(
            name='CompositionCategory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('position', models.PositiveIntegerField(default=0, help_text="Lower numbers appear first in this composition's category list.")),
                ('category', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='compositions.category')),
                ('composition', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='category_memberships', to='compositions.composition')),
            ],
            options={
                'ordering': ['position', 'pk'],
                'verbose_name': 'composition category',
                'verbose_name_plural': 'composition categories',
                'constraints': [models.UniqueConstraint(fields=('composition', 'category'), name='unique_composition_category')],
            },
        ),
        migrations.RunPython(copy_memberships, restore_memberships),
        migrations.RemoveField(model_name='composition', name='categories'),
        migrations.AddField(
            model_name='composition', name='categories',
            field=models.ManyToManyField(blank=True, related_name='compositions', through='compositions.CompositionCategory', to='compositions.category'),
        ),
    ]
