from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="KurlyFaq",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("faq_no", models.PositiveIntegerField(db_index=True, unique=True)),
                ("category", models.CharField(max_length=100)),
                ("question", models.TextField()),
                ("answer", models.TextField()),
                ("question_html", models.TextField()),
                ("answer_html", models.TextField()),
                ("source_url", models.URLField()),
                ("crawled_at", models.DateTimeField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "faqs_kurlyfaq",
                "ordering": ["-faq_no"],
            },
        ),
    ]
