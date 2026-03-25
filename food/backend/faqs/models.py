from django.db import models


class KurlyFaq(models.Model):
    faq_no = models.PositiveIntegerField(unique=True, db_index=True)
    category = models.CharField(max_length=100)
    question = models.TextField()
    answer = models.TextField()
    question_html = models.TextField()
    answer_html = models.TextField()
    source_url = models.URLField()
    crawled_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "faqs_kurlyfaq"
        ordering = ["-faq_no"]

    def __str__(self) -> str:
        return f"{self.faq_no} - {self.question}"
