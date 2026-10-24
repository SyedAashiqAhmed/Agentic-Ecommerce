from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import requests
import streamlit as st

from agents.buyer_agent import BuyerAgent
from agents.seller_agent import SellerAgent
from business.agreement import record_agreement
from business.chat_policy import validate_chat_proposal
from business.negotiation import NegotiationEngine
from business.recovery import RecoveryManager
from business.transaction import TransactionState, TransactionStateMachine
from business.trust import verify_integrity
from business.verification import verify_agreement
from chat_client import (
    ChatSocketError,
    check_chat_connection,
    create_chat_room,
    exchange_agent_message,
    send_chat_message,
    set_chat_permission,
)
from data import demo_sellers
from llm.ollama_client import OllamaClient, OllamaError
from schemas import NegotiationMessage


st.set_page_config(
    page_title="CommerceOS",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

CHAT_HEALTH_URL = "http://127.0.0.1:8765/health"
CHAT_HOST = "127.0.0.1"
CHAT_PORT = 8765
NAVIGATION = [
    "Overview",
    "Buyer Workspace",
    "Agent Negotiations",
    "Seller Portal",
    "Approvals",
    "Conversations",
    "Agreements & Verification",
    "Transaction History",
]


def _chat_health(timeout: float = 6) -> str | None:
    try:
        response = requests.get(CHAT_HEALTH_URL, timeout=timeout)
        response.raise_for_status()
        if response.json().get("status") == "ok":
            return None
        return f"unexpected health response: {response.text}"
    except (requests.RequestException, ValueError, TypeError) as exc:
        return str(exc)


def _chat_port_open() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex((CHAT_HOST, CHAT_PORT)) == 0


def ensure_chat_server() -> None:
    if _chat_health() is None:
        return
    if _chat_port_open():
        for _ in range(10):
            if _chat_health() is None:
                return
            time.sleep(0.5)
        raise ChatSocketError(
            "Port 8765 is occupied, but the existing service is not healthy."
        )
    process = st.session_state.get("chat_server_process")
    if process is None or process.poll() is not None:
        root = Path(__file__).parent
        process = subprocess.Popen(
            [sys.executable, str(root / "chat_server.py")],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        st.session_state.chat_server_process = process
    for _ in range(20):
        health_error = _chat_health()
        if health_error is None:
            return
        if process.poll() is not None:
            stderr = (process.stderr.read() if process.stderr else "").strip()
            raise ChatSocketError(
                f"Chat service exited during startup: {stderr or health_error}"
            )
        time.sleep(0.5)
    raise ChatSocketError(
        f"Chat service did not become healthy on port 8765: {_chat_health()}"
    )


def initialize_state() -> None:
    defaults = {
        "result": None,
        "request_text": "",
        "transaction_machine": TransactionStateMachine(),
        "chat_socket_status": "not connected",
        "agent_messages": {},
        "direct_messages": {},
        "agreement": None,
        "transaction_history": [],
        "checkout_authorized": False,
        "pending_navigation": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def current_bundle():
    if not st.session_state.result:
        return None
    return st.session_state.result


def sellers_and_products():
    sellers = [SellerAgent(profile, llm=st.session_state.ollama if st.session_state.ollama_ready else None) for profile in demo_sellers()]
    products = {product.product_id: product for seller in sellers for product in seller.profile.products}
    return sellers, products


def prepare_chat_rooms(request, result, products) -> None:
    if not result.selected_offer:
        return
    offer = result.selected_offer
    if not result.chat_room_id:
        result.chat_room_id = offer.offer_id
    if not result.direct_chat_room_id:
        result.direct_chat_room_id = f"{result.chat_room_id}-direct"
    profile = next(profile for profile in demo_sellers() if profile.seller_id == offer.seller_id)
    ensure_chat_server()
    create_chat_room(
        result.chat_room_id,
        buyer_context={
            "role": "buyer procurement agent",
            "request": request.model_dump(),
            "hard_constraints": request.hard_constraints,
            "budget_inr": request.max_budget_inr,
        },
        supplier_context={
            "role": "supplier agent",
            "supplier_id": profile.seller_id,
            "supplier_name": profile.display_name,
            "private_policies": profile.policies[offer.product_id].model_dump(),
            "product": products[offer.product_id].model_dump(),
        },
        agent_chat_enabled=True,
    )
    create_chat_room(
        result.direct_chat_room_id,
        buyer_context={"role": "buyer human", "request": request.model_dump()},
        supplier_context={"role": "seller human", "supplier_id": profile.seller_id},
        agent_chat_enabled=False,
    )


def page_header(title: str, description: str) -> None:
    st.title(title)
    st.caption(description)
    st.divider()


def status_badge(label: str, state: str) -> None:
    colors = {
        "success": ("#dcfce7", "#166534"),
        "warning": ("#fef3c7", "#92400e"),
        "error": ("#fee2e2", "#991b1b"),
        "info": ("#dbeafe", "#1e40af"),
    }
    background, foreground = colors.get(state, colors["info"])
    st.markdown(
        f'<span style="background:{background};color:{foreground};padding:5px 10px;border-radius:999px;font-weight:600;font-size:.85rem">{label}</span>',
        unsafe_allow_html=True,
    )


def render_transaction_context(request, result) -> None:
    if not result or not result.selected_offer:
        return
    offer = result.selected_offer
    st.caption(
        f"Transaction `{offer.offer_id[:8]}` · Seller `{offer.seller_id}` · "
        f"{offer.quantity} unit(s) · ₹{offer.total_price_inr:,}"
    )


def render_offer(offer, products, selected_offer) -> None:
    product = products[offer.product_id]
    with st.container(border=True):
        left, middle, right = st.columns([2, 1, 1])
        left.write(f"**{offer.seller_id}** — {product.name}")
        left.caption(f"{product.rating}★ · {product.review_count:,} reviews · {product.stock} in stock")
        middle.metric("Total", f"₹{offer.total_price_inr:,}")
        right.metric("Delivery", f"{offer.delivery_days} days")
        if offer == selected_offer:
            status_badge("Recommended offer", "success")
        elif offer.status == "rejected":
            status_badge("Rejected", "error")
        else:
            status_badge("Offer received", "info")
        if offer.requires_seller_approval and offer.seller_approval_status != "approved":
            st.warning("Seller approval is required because this price is below the automatic approval floor.")


def run_purchase_request(text: str, ollama: OllamaClient, ollama_ready: bool) -> None:
    if not text.strip():
        st.error("Describe what you want to buy first.")
        return
    with st.status("Running autonomous procurement…", expanded=True) as progress:
        try:
            ensure_chat_server()
            progress.write("Buyer Agent is extracting requirements…")
            buyer = BuyerAgent(llm=ollama if ollama_ready else None)
            request = buyer.parse_request(text)
            progress.write("Supplier Agents are checking inventory and negotiating…")
            sellers, products = sellers_and_products()
            result = NegotiationEngine(buyer).run(request, sellers, products)
            st.session_state.transaction_machine = TransactionStateMachine()
            st.session_state.transaction_machine.transition(TransactionState.NEGOTIATING)
            prepare_chat_rooms(request, result, products)
            st.session_state.result = (request, result, products, buyer)
            st.session_state.agent_messages = {}
            st.session_state.direct_messages = {}
            st.session_state.agreement = None
            st.session_state.checkout_authorized = False
            st.session_state.transaction_history.insert(0, {
                "id": result.selected_offer.offer_id if result.selected_offer else "no-offer",
                "status": "negotiating" if result.selected_offer else "no compliant offer",
                "seller": result.selected_offer.seller_id if result.selected_offer else "—",
                "total": result.selected_offer.total_price_inr if result.selected_offer else 0,
            })
            progress.update(label="Procurement request ready", state="complete", expanded=False)
        except (ChatSocketError, OllamaError, ValueError, RuntimeError) as exc:
            progress.update(label="Procurement request failed", state="error", expanded=True)
            st.error(f"CommerceOS could not complete the request: {exc}")


def render_overview() -> None:
    page_header("CommerceOS command center", "One clear view of requests, approvals, negotiations, and agreement safety.")
    bundle = current_bundle()
    result = bundle[1] if bundle else None
    active = bool(result and result.selected_offer)
    pending_approval = bool(
        result and result.selected_offer and
        result.selected_offer.requires_seller_approval and
        result.selected_offer.seller_approval_status != "approved"
    )
    chat_request = bool(result and result.supplier_chat_status == "pending")
    metrics = [
        ("Active request", "1" if active else "0"),
        ("Agents negotiating", str(len(result.offers) + 1) if result else "0"),
        ("Pending approvals", str(int(pending_approval) + int(chat_request))),
        ("Checkout status", "Blocked" if not st.session_state.checkout_authorized else "Authorized"),
    ]
    cols = st.columns(4)
    for col, (label, value) in zip(cols, metrics):
        col.metric(label, value)
    if not active:
        st.info("Nothing is running yet. Start with **Create Purchase Request**.")
        if st.button("Create Purchase Request", type="primary"):
            st.session_state.pending_navigation = "Buyer Workspace"
            st.rerun()
        return
    request, result, products, buyer = bundle
    st.subheader("Current transaction")
    render_transaction_context(request, result)
    st.write(f"**Buyer need:** {request.original_text}")
    st.write(f"**Current state:** `{st.session_state.transaction_machine.state.value}`")
    next_step = "Review seller approval" if pending_approval else "Review the recommended offer"
    st.info(f"Next step: **{next_step}**. Use the navigation on the left.")
    if chat_request:
        st.warning("A supplier has requested direct contact. Review it in Buyer Workspace.")


def render_buyer_workspace(ollama, ollama_ready) -> None:
    page_header("Buyer Workspace", "Describe the purchase. CommerceOS extracts constraints, negotiates, and protects your budget.")
    text = st.text_area(
        "What do you need?",
        value=st.session_state.request_text or "Find a gaming laptop with an RTX 3050 or better, at least 16 GB RAM, under ₹70,000. Prioritize ratings and reviews.",
        height=120,
        key="purchase_request_text",
    )
    if st.button("Create Purchase Request", type="primary"):
        st.session_state.request_text = text
        run_purchase_request(text, ollama, ollama_ready)
    bundle = current_bundle()
    if not bundle:
        st.info("Your extracted requirements and supplier offers will appear here after submission.")
        return
    request, result, products, buyer = bundle
    st.subheader("Buyer Agent interpretation")
    a, b, c = st.columns(3)
    a.metric("Category", request.product_category)
    b.metric("Quantity", request.quantity)
    c.metric("Maximum budget", f"₹{request.max_budget_inr:,}")
    st.write("**Mandatory requirements:**", request.hard_constraints or "None extracted")
    st.write("**Preferences:**", ", ".join(request.preferences) or "None")
    if buyer.last_error:
        st.warning(f"Gemma output was rejected and fallback parsing was used: {buyer.last_error}")
    st.subheader("Eligible supplier offers")
    for offer in result.offers:
        render_offer(offer, products, result.selected_offer)
    if result.selected_offer:
        st.success(f"Recommended: {result.selected_offer.seller_id} at ₹{result.selected_offer.total_price_inr:,} total.")
    else:
        st.error(result.reason)
    if result.supplier_chat_status == "pending" and result.supplier_chat_request:
        st.subheader("Supplier direct-chat request")
        st.info(f"**Why:** {result.supplier_chat_request}")
        st.caption("This is separate from autonomous AI negotiation. Direct chat opens only after acceptance.")
        accept, decline = st.columns(2)
        if accept.button("Accept Chat Request", type="primary"):
            try:
                set_chat_permission(result.direct_chat_room_id, True)
                result.supplier_chat_status = "approved"
                st.session_state.result = (request, result, products, buyer)
                st.success("Direct conversation opened. Go to Conversations.")
                st.rerun()
            except ChatSocketError as exc:
                st.error(f"Could not open direct conversation: {exc}")
        if decline.button("Decline Chat Request"):
            try:
                set_chat_permission(result.direct_chat_room_id, False)
            except ChatSocketError as exc:
                st.error(str(exc))
            result.supplier_chat_status = "rejected"
            st.session_state.result = (request, result, products, buyer)
            st.rerun()


def render_agent_negotiations() -> None:
    page_header("Agent Negotiations", "Observe the real Buyer Agent and Supplier Agent negotiation. Human approval is not needed for ordinary AI messages.")
    bundle = current_bundle()
    if not bundle:
        st.info("Create a purchase request to start an agent negotiation.")
        return
    request, result, products, buyer = bundle
    render_transaction_context(request, result)
    st.subheader("Negotiation timeline")
    for message in result.messages:
        with st.container(border=True):
            role = {"buyer_agent": "Buyer Agent", "seller_agent": "Supplier Agent", "system": "System"}.get(message.sender_role, message.sender_role)
            st.caption(f"{role} · Round {message.round_number} · {message.message_type}")
            st.write(message.message)
    st.subheader("Current decision")
    if result.selected_offer:
        render_offer(result.selected_offer, products, result.selected_offer)
    for reason in result.decision_trace:
        st.write(f"• {reason}")
    if result.chat_room_id:
        st.info("Need clarification? The buyer can message the Supplier Agent in this AI negotiation room. Direct human chat is a separate permissioned conversation.")
        prompt = st.text_input("Message Supplier Agent", key="agent_negotiation_prompt")
        if st.button("Send to Supplier Agent") and prompt.strip():
            try:
                messages = send_chat_message(result.chat_room_id, "buyer-user", prompt, result.selected_offer.round_number)
                st.session_state.agent_messages.setdefault(result.chat_room_id, []).extend(messages)
                st.rerun()
            except ChatSocketError as exc:
                st.error(str(exc))
        for item in st.session_state.agent_messages.get(result.chat_room_id, []):
            st.chat_message("user" if item["sender_role"] == "buyer-user" else "assistant").write(item["message"])


def render_seller_portal(ollama, ollama_ready) -> None:
    page_header("Seller Portal", "Manage your catalog, policies, active AI negotiations, and requests for buyer contact.")
    sellers, products = sellers_and_products()
    st.subheader("Seller catalog")
    for seller in sellers:
        with st.expander(f"{seller.profile.display_name} · {seller.profile.seller_id}", expanded=True):
            for product in seller.profile.products:
                policy = seller.profile.policies[product.product_id]
                st.write(f"**{product.name}** · {product.stock} in stock · ₹{product.listed_price_inr:,} listed · {product.delivery_days} days")
                st.caption(f"Hard minimum ₹{policy.minimum_price_inr:,} · Automatic approval floor ₹{policy.automatic_approval_floor_inr:,}")
    bundle = current_bundle()
    if not bundle:
        st.info("Active negotiations will appear here after a buyer creates a request.")
        return
    request, result, products, buyer = bundle
    if not result.selected_offer:
        st.info("No compliant offer is currently available.")
        return
    offer = result.selected_offer
    seller = next(s for s in sellers if s.profile.seller_id == offer.seller_id)
    st.subheader("Active negotiation")
    st.write(f"**Buyer request:** {request.original_text}")
    render_offer(offer, products, offer)
    if result.supplier_chat_status == "pending":
        st.warning("The Supplier Agent has requested direct buyer contact. The buyer must accept it in Buyer Workspace.")
    elif result.supplier_chat_status == "approved":
        st.success("Direct buyer conversation approved. Open Conversations.")
    elif st.button("Request Direct Chat with Buyer"):
        try:
            request_text = seller.request_direct_chat(request, products[offer.product_id], offer)
            result.supplier_chat_request = request_text
            result.supplier_chat_status = "pending"
            st.session_state.result = (request, result, products, buyer)
            st.rerun()
        except (OllamaError, ValueError) as exc:
            st.error(f"Supplier Agent could not create a request: {exc}")
    if offer.requires_seller_approval and offer.seller_approval_status != "approved":
        st.warning("This offer needs seller approval. Review it in Approvals.")


def render_approvals() -> None:
    page_header("Approvals", "Only policy-sensitive actions appear here. Ordinary agent conversation does not require manual approval.")
    bundle = current_bundle()
    if not bundle:
        st.info("There are no approval requests.")
        return
    request, result, products, buyer = bundle
    offer = result.selected_offer
    if not offer:
        st.info("There are no approval requests.")
        return
    if not offer.requires_seller_approval or offer.seller_approval_status == "approved":
        st.success("No pending seller approval.")
        return
    seller = next(profile for profile in demo_sellers() if profile.seller_id == offer.seller_id)
    policy = seller.policies[offer.product_id]
    st.warning(f"Seller approval required for {offer.seller_id}: ₹{offer.unit_price_inr:,}/unit is below the automatic floor.")
    st.write(f"**Buyer:** procurement request · **Product:** {products[offer.product_id].name} · **Quantity:** {offer.quantity}")
    st.write(f"**Policy trigger:** automatic floor ₹{policy.automatic_approval_floor_inr:,}; hard minimum ₹{policy.minimum_price_inr:,}.")
    approve, reject = st.columns(2)
    if approve.button("Approve Offer", type="primary"):
        result.selected_offer = offer.model_copy(update={"seller_approval_status": "approved"})
        result.events.append("Seller human approval granted.")
        result.messages.append(NegotiationMessage(
            sender_id="seller-human",
            sender_role="seller_human",
            message="Seller approved the negotiated commercial terms.",
            round_number=offer.round_number,
            message_type="approval_response",
            related_offer_id=offer.offer_id,
        ))
        st.session_state.result = (request, result, products, buyer)
        st.rerun()
    if reject.button("Reject Offer"):
        result.selected_offer = offer.model_copy(update={"seller_approval_status": "rejected", "status": "rejected"})
        result.events.append("Seller human rejected the offer.")
        st.session_state.result = (request, result, products, buyer)
        st.rerun()


def render_conversations() -> None:
    page_header("Conversations", "AI negotiation and direct human communication are separate threads linked to the same transaction.")
    bundle = current_bundle()
    if not bundle:
        st.info("Create a purchase request first.")
        return
    request, result, products, buyer = bundle
    if result.supplier_chat_status != "approved" or not result.direct_chat_room_id:
        st.info("No direct conversation is open. The buyer must accept a supplier request in Buyer Workspace.")
        return
    offer = result.selected_offer
    st.success(f"Direct conversation · transaction {offer.offer_id[:8]} · connected participants")
    try:
        check_chat_connection(result.direct_chat_room_id, "buyer-human")
        st.session_state.chat_socket_status = "connected"
    except ChatSocketError as exc:
        st.session_state.chat_socket_status = f"offline: {exc}"
    st.caption(f"WebSocket status: {st.session_state.chat_socket_status}")
    participant = st.radio("Send as", ["Buyer (human)", "Seller (human)"], horizontal=True)
    role = "buyer-human" if participant.startswith("Buyer") else "seller-human"
    for message in st.session_state.direct_messages.get(result.direct_chat_room_id, []):
        label = {
            "buyer-human": "Buyer · human",
            "seller-human": "Seller · human",
            "buyer-agent": "Buyer Agent",
            "supplier-agent": "Supplier Agent",
        }.get(message["sender_role"], "System")
        with st.chat_message("user" if "human" in message["sender_role"] else "assistant"):
            st.caption(label)
            st.write(message["message"])
            if message.get("proposal"):
                st.warning(f"Unapplied proposal: {message['proposal']}")
    text = st.chat_input("Write a direct message…", key="direct_conversation_input")
    if text:
        try:
            messages = send_chat_message(result.direct_chat_room_id, role, text, offer.round_number)
            st.session_state.direct_messages.setdefault(result.direct_chat_room_id, []).extend(messages)
            st.rerun()
        except ChatSocketError as exc:
            st.error(f"Message was not sent: {exc}")
    st.divider()
    st.caption("A chat proposal never changes the offer automatically. It must pass deterministic policy validation and then return to Approvals.")
    proposals = [item for item in st.session_state.direct_messages.get(result.direct_chat_room_id, []) if item.get("proposal")]
    if proposals:
        seller = next(profile for profile in demo_sellers() if profile.seller_id == offer.seller_id)
        policy = seller.policies[offer.product_id]
        product = products[offer.product_id]
        for item in proposals:
            valid, errors = validate_chat_proposal(item["proposal"], request, offer, product, policy)
            if valid:
                st.success(f"Policy-valid proposal awaiting explicit application: {item['proposal']}")
            else:
                st.error(f"Proposal rejected: {', '.join(errors)}")


def render_agreements() -> None:
    page_header("Agreements & Verification", "Accepted terms are hashed, versioned, and checked before simulated checkout.")
    bundle = current_bundle()
    if not bundle or not bundle[1].selected_offer:
        st.info("There is no accepted offer to verify.")
        return
    request, result, products, buyer = bundle
    offer = result.selected_offer
    if offer.requires_seller_approval and offer.seller_approval_status != "approved":
        st.error("Agreement recording is blocked until seller approval is complete.")
        return
    if st.session_state.agreement is None:
        st.session_state.agreement = record_agreement(offer)
    agreement = st.session_state.agreement
    integrity = verify_integrity(agreement)
    st.subheader("Accepted agreement")
    st.json(agreement.model_dump())
    status_badge("Integrity verified" if integrity.passed else "Integrity failed", "success" if integrity.passed else "error")
    if integrity.passed and st.button("Authorize simulated checkout", type="primary"):
        st.session_state.checkout_authorized = True
        st.session_state.transaction_machine.transition(TransactionState.FULFILLED)
        st.success("Simulated checkout authorized. No real payment was processed.")
    changed = offer.model_copy(update={"unit_price_inr": offer.unit_price_inr + 2000, "total_price_inr": (offer.unit_price_inr + 2000) * offer.quantity})
    verification = verify_agreement(agreement, changed)
    st.subheader("Tamper detection")
    if verification.passed:
        st.success("No mismatch detected.")
    else:
        st.error("Checkout blocked: " + "; ".join(verification.mismatches))
        fallback = next((candidate for candidate in result.offers if candidate.seller_id != offer.seller_id), None)
        if st.button("Record payment block and recover"):
            recovery = RecoveryManager()
            recovered, recovered_agreement = recovery.detect_and_recover(agreement, changed, fallback)
            st.session_state.transaction_machine.transition(TransactionState.PAYMENT_BLOCKED)
            if recovered and recovered_agreement:
                st.session_state.transaction_machine.transition(TransactionState.RECOVERED)
                st.success("Recovery recorded and a new agreement version was created.")
                st.json(recovered_agreement.model_dump())


def render_history() -> None:
    page_header("Transaction History", "Every run remains visible with its current status and transaction identifier.")
    if not st.session_state.transaction_history:
        st.info("No transactions yet.")
        return
    for item in st.session_state.transaction_history:
        with st.container(border=True):
            st.write(f"**Transaction:** `{item['id']}`")
            st.write(f"Seller: {item['seller']} · Total: ₹{item['total']:,} · Status: **{item['status']}**")


initialize_state()
ollama = OllamaClient()
st.session_state.ollama = ollama
st.session_state.ollama_ready = ollama.is_available()
if st.session_state.pending_navigation:
    st.session_state.navigation = st.session_state.pending_navigation
    st.session_state.pending_navigation = None

with st.sidebar:
    st.markdown("## ◈ CommerceOS")
    st.caption("Autonomous AI Commerce Network")
    page = st.radio("Workspace", NAVIGATION, key="navigation", label_visibility="collapsed")
    st.divider()
    status_badge("Gemma 3 4B online" if st.session_state.ollama_ready else "Gemma offline", "success" if st.session_state.ollama_ready else "warning")
    st.caption("Local Ollama inference · deterministic policy enforcement")

if page == "Overview":
    render_overview()
elif page == "Buyer Workspace":
    render_buyer_workspace(ollama, st.session_state.ollama_ready)
elif page == "Agent Negotiations":
    render_agent_negotiations()
elif page == "Seller Portal":
    render_seller_portal(ollama, st.session_state.ollama_ready)
elif page == "Approvals":
    render_approvals()
elif page == "Conversations":
    render_conversations()
elif page == "Agreements & Verification":
    render_agreements()
else:
    render_history()
