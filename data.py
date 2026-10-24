from schemas import Product, SellerPolicy, SellerProfile


def demo_sellers() -> list[SellerProfile]:
    return [
        SellerProfile(
            seller_id="seller-nova",
            display_name="Nova Electronics",
            products=[
                Product(
                    product_id="nova-laptop-1", name="Nova RTX Gaming Laptop", category="laptop",
                    description="Gaming laptop for work and play.",
                    attributes={"ram_gb": 16, "gpu": "RTX 3050", "storage_gb": 512},
                    listed_price_inr=68500, stock=4, delivery_days=3, rating=4.6, review_count=842,
                ),
            ],
            policies={
                "nova-laptop-1": SellerPolicy(
                    minimum_price_inr=64000, automatic_approval_floor_inr=66500,
                    seller_instructions="Negotiate politely and confirm stock before accepting.",
                ),
            },
        ),
        SellerProfile(
            seller_id="seller-orbit",
            display_name="Orbit Digital",
            products=[
                Product(
                    product_id="orbit-laptop-1", name="Orbit RTX Performance Laptop", category="laptop",
                    description="High-value gaming laptop with fast delivery.",
                    attributes={"ram_gb": 16, "gpu": "RTX 3050", "storage_gb": 512},
                    listed_price_inr=67000, stock=2, delivery_days=6, rating=4.2, review_count=1240,
                ),
            ],
            policies={
                "orbit-laptop-1": SellerPolicy(
                    minimum_price_inr=62000, automatic_approval_floor_inr=67000,
                    seller_instructions="Never sell below the minimum price. Approval is required for deeper discounts.",
                ),
            },
        ),
    ]
