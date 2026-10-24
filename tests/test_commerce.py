from agents.buyer_agent import BuyerAgent
from agents.seller_agent import SellerAgent
from business.agreement import record_agreement
from business.verification import verify_agreement
from data import demo_sellers
from business.negotiation import NegotiationEngine
from business.recovery import RecoveryManager
from business.trust import verify_integrity


def test_seller_never_accepts_below_hard_floor():
    seller = SellerAgent(demo_sellers()[0])
    product = seller.profile.products[0]
    request = BuyerAgent().parse_request("one laptop under ₹70000")
    offer = seller.respond_to_counteroffer(request, product, 1, 2)
    assert offer.status == "rejected"


def test_agreement_detects_changed_price():
    seller = SellerAgent(demo_sellers()[0])
    product = seller.profile.products[0]
    request = BuyerAgent().parse_request("one laptop under ₹70000")
    offer = seller.create_offer(request, product)
    agreement = record_agreement(offer)
    changed = offer.model_copy(update={"unit_price_inr": offer.unit_price_inr + 1, "total_price_inr": offer.total_price_inr + 1})
    result = verify_agreement(agreement, changed)
    assert not result.passed
    assert any("unit_price_inr" in mismatch for mismatch in result.mismatches)


def test_demo_sellers_have_compliant_initial_offers():
    sellers = [SellerAgent(profile) for profile in demo_sellers()]
    request = BuyerAgent().parse_request("gaming laptop with at least 16 GB RAM under ₹70000")
    offers = [seller.create_offer(request, seller.profile.products[0]) for seller in sellers]
    assert all(offer is not None for offer in offers)


def test_gpu_min_constraint_supports_model_tiers():
    buyer = BuyerAgent()
    request = buyer.parse_request("gaming laptop under ₹70000")
    request = request.model_copy(update={"hard_constraints": {"gpu_min": "RTX 3050"}})
    products = demo_sellers()[0].products
    assert buyer.filter_products(request, products)


def test_negotiation_runs_a_bounded_counteroffer():
    buyer = BuyerAgent()
    sellers = [SellerAgent(profile) for profile in demo_sellers()]
    products = {product.product_id: product for seller in sellers for product in seller.profile.products}
    request = buyer.parse_request("gaming laptop with at least 16 GB RAM under ₹70000")
    result = NegotiationEngine(buyer).run(request, sellers, products)
    assert result.selected_offer is not None
    assert any("countered" in event for event in result.events)
    assert result.selected_offer.round_number <= 3


def test_discount_below_approval_floor_requires_seller_approval():
    seller = SellerAgent(demo_sellers()[1])
    product = seller.profile.products[0]
    request = BuyerAgent().parse_request("gaming laptop under ₹70000")
    offer = seller.respond_to_counteroffer(request, product, 65000, 2)
    assert offer.requires_seller_approval
    assert offer.seller_approval_status == "pending"
    approved = seller.approve(offer)
    assert approved.seller_approval_status == "approved"


def test_agreement_has_sha256_integrity_record():
    seller = SellerAgent(demo_sellers()[0])
    request = BuyerAgent().parse_request("gaming laptop under ₹70000")
    offer = seller.create_offer(request, seller.profile.products[0])
    agreement = record_agreement(offer)
    assert agreement.integrity is not None
    assert len(agreement.integrity.sha256) == 64
    assert verify_integrity(agreement).passed


def test_recovery_creates_new_agreement_version_after_tampering():
    sellers = [SellerAgent(profile) for profile in demo_sellers()]
    request = BuyerAgent().parse_request("gaming laptop under ₹70000")
    offers = [seller.create_offer(request, seller.profile.products[0]) for seller in sellers]
    agreement = record_agreement(offers[0])
    changed = offers[0].model_copy(update={
        "unit_price_inr": offers[0].unit_price_inr + 1000,
        "total_price_inr": offers[0].total_price_inr + 1000,
    })
    recovered, replacement = RecoveryManager().detect_and_recover(agreement, changed, offers[1])
    assert recovered
    assert replacement is not None
    assert replacement.version == 2
    assert replacement.seller_id != agreement.seller_id


def test_negotiation_produces_structured_agent_chat():
    buyer = BuyerAgent()
    sellers = [SellerAgent(profile) for profile in demo_sellers()]
    products = {product.product_id: product for seller in sellers for product in seller.profile.products}
    request = buyer.parse_request("gaming laptop with at least 16 GB RAM under ₹70000")
    result = NegotiationEngine(buyer).run(request, sellers, products)
    roles = {message.sender_role for message in result.messages}
    assert "buyer_agent" in roles
    assert "seller_agent" in roles
    assert any(message.message_type == "counteroffer" for message in result.messages)
