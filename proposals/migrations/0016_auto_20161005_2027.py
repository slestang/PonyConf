# -*- coding: utf-8 -*-
# Generated by Django 1.10 on 2016-10-05 20:27
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('proposals', '0015_auto_20161005_1932'),
    ]

    operations = [
        migrations.AlterField(
            model_name='event',
            name='duration',
            field=models.IntegerField(default=0, verbose_name='Duration (min)'),
        ),
        migrations.AlterField(
            model_name='talk',
            name='duration',
            field=models.IntegerField(default=0, verbose_name='Duration (min)'),
        ),
    ]
