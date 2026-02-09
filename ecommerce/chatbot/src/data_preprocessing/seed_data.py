import os
import sys
from datetime import datetime
from decimal import Decimal
from sqlalchemy.orm import Session

# Add the project root to the python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from ecommerce.platform.backend.app.database import SessionLocal, engine, Base
from ecommerce.platform.backend.app.router.users.models import User, UserStatus
from ecommerce.platform.backend.app.router.shipping.models import ShippingAddress
from ecommerce.platform.backend.app.db.models import (
    Category, Product, ProductOption, Order, OrderItem, 
    Payment, PaymentStatus, OrderStatus, ProductType, ShippingInfo
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def seed_data():
    db = next(get_db())
    
    print("creating tables...")
    Base.metadata.create_all(bind=engine)

    try:
        # 1. Create User
        print("Checking user...")
        user = db.query(User).filter(User.email == "test@example.com").first()
        if not user:
            user = User(
                email="test@example.com",
                password_hash="hashed_password", 
                name="Test User",
                phone="010-1234-5678",
                status=UserStatus.ACTIVE,
                agree_marketing=True,
                agree_sms=True,
                agree_email=True
            )
            db.add(user)
            db.flush()
            print(f"Created user: {user.name}")
        
        # 2. Create Shipping Address
        print("Checking shipping address...")
        shipping_address = db.query(ShippingAddress).filter(ShippingAddress.user_id == user.id).first()
        if not shipping_address:
            shipping_address = ShippingAddress(
                user_id=user.id,
                recipient_name="Test Recipient",
                address1="Seoul, Gangnam-gu",
                address2="Teheran-ro 123",
                post_code="06123",
                phone="010-1234-5678",
                is_default=True
            )
            db.add(shipping_address)
            db.flush()
            print(f"Created shipping address for user: {user.name}")

        # 3. Create Categories
        print("Checking categories...")
        top_category = db.query(Category).filter(Category.name == "Top").first()
        if not top_category:
            top_category = Category(name="Top", display_order=1)
            db.add(top_category)
            db.flush()
            print("Created category: Top")
        
        bottom_category = db.query(Category).filter(Category.name == "Bottom").first()
        if not bottom_category:
            bottom_category = Category(name="Bottom", display_order=2)
            db.add(bottom_category)
            db.flush()
            print("Created category: Bottom")

        # 4. Create Products & Options
        print("Checking products...")
        
        # T-Shirt
        tshirt = db.query(Product).filter(Product.name == "Basic T-Shirt").first()
        if not tshirt:
            tshirt = Product(
                category_id=top_category.id, # type: ignore
                name="Basic T-Shirt",
                description="A comfortable cotton t-shirt",
                price=Decimal("19.99"),
                is_active=True
            )
            db.add(tshirt)
            db.flush()
            print("Created product: Basic T-Shirt")

        # Ensure T-Shirt Options
        if not db.query(ProductOption).filter(ProductOption.sku == "TS-WH-M").first():
            db.add(ProductOption(product_id=tshirt.id, size_name="M", color="White", quantity=100, sku="TS-WH-M"))
        if not db.query(ProductOption).filter(ProductOption.sku == "TS-BK-L").first():
            db.add(ProductOption(product_id=tshirt.id, size_name="L", color="Black", quantity=50, sku="TS-BK-L"))
        db.flush()

        # Jeans
        jeans = db.query(Product).filter(Product.name == "Classic Jeans").first()
        if not jeans:
            jeans = Product(
                category_id=bottom_category.id, # type: ignore
                name="Classic Jeans",
                description="Durable denim jeans",
                price=Decimal("49.99"),
                is_active=True
            )
            db.add(jeans)
            db.flush()
            print("Created product: Classic Jeans")

        # Ensure Jeans Options
        if not db.query(ProductOption).filter(ProductOption.sku == "JN-BL-32").first():
            db.add(ProductOption(product_id=jeans.id, size_name="32", color="Blue", quantity=30, sku="JN-BL-32"))
        db.flush()

        # 5. Create Order
        print("Checking orders...")
        existing_order = db.query(Order).filter(Order.order_number == "ORD-20240209-0001").first()
        if not existing_order:
            # Re-query options to get IDs
            option_tshirt = db.query(ProductOption).filter(ProductOption.sku == "TS-WH-M").first()
            option_jeans = db.query(ProductOption).filter(ProductOption.sku == "JN-BL-32").first()
            
            if not option_tshirt or not option_jeans:
                raise ValueError("Product options not found!")

            order = Order(
                user_id=user.id,
                order_number="ORD-20240209-0001",
                shipping_address_id=shipping_address.id,
                subtotal=Decimal("69.98"), # 19.99 + 49.99
                total_amount=Decimal("69.98"),
                status=OrderStatus.DELIVERED,
                payment_method="Credit Card",
                created_at=datetime.now()
            )
            db.add(order)
            db.flush()

            # Order Items
            db.add(OrderItem(
                order_id=order.id,
                product_option_type=ProductType.NEW,
                product_option_id=option_tshirt.id,
                quantity=1,
                unit_price=Decimal("19.99"),
                subtotal=Decimal("19.99")
            ))
            db.add(OrderItem(
                order_id=order.id,
                product_option_type=ProductType.NEW,
                product_option_id=option_jeans.id,
                quantity=1,
                unit_price=Decimal("49.99"),
                subtotal=Decimal("49.99")
            ))

            # Payment
            db.add(Payment(
                order_id=order.id,
                payment_method="Credit Card",
                payment_status=PaymentStatus.COMPLETED
            ))

            # Shipping Info
            db.add(ShippingInfo(
                order_id=order.id,
                courier_company="FastDelivery",
                tracking_number="Tracking-123456789",
                shipped_at=datetime.utcnow(),
                delivered_at=datetime.utcnow()
            ))
            
            print(f"Created order: {order.order_number}")

        db.commit()
        print("Successfully seeded data!")

    except Exception as e:
        db.rollback()
        print(f"Error seeding data: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    seed_data()
