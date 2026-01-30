from django.db import models
import uuid

class TelegramUser(models.Model):
    telegram_id = models.BigIntegerField(unique=True)
    username = models.CharField(max_length=255, blank=True)
    first_name = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.first_name} ({self.telegram_id})"

class Order(models.Model):
    STATUS_CHOICES = [
        ('new', 'Yangi'),
        ('accepted', 'Qabul qilindi'),
        ('delivered', 'Yetkazildi'),
        ('cancelled', 'Bekor qilindi'),
    ]
    
    order_id = models.CharField(max_length=50, unique=True, default=uuid.uuid4)
    user = models.ForeignKey(TelegramUser, on_delete=models.CASCADE)
    items = models.TextField(default='[]')
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    address = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Buyurtma #{self.order_id}"