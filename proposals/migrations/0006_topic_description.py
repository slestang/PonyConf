# -*- coding: utf-8 -*-
# Generated by Django 1.10 on 2016-08-07 07:50
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('proposals', '0005_auto_20160723_1216'),
    ]

    operations = [
        migrations.AddField(
            model_name='topic',
            name='description',
            field=models.TextField(blank=True, verbose_name='Description'),
        ),
    ]
