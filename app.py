import subprocess
import sys
import time
import socket
from pathlib import Path

import requests
import streamlit as st

from agents.buyer_agent import BuyerAgent
from agents.seller_agent import SellerAgent
from business.chat_policy import validate_chat_proposal
from chat_client import (
    ChatSocketError,
    check_chat_connection,
    create_chat_room,
    exchange_agent_message,
    send_seller_message,
    set_chat_permission,
    send_chat_message,
)
from business.agreement import record_agreement
from business.negotiation import NegotiationEngine
from business.recovery import RecoveryManager
from business.transaction import TransactionState, TransactionStateMachine
from business.trust import verify_integrity
from business.verification import verify_agreement
from data import demo_sellers
from llm.ollama_client import OllamaClient, OllamaError
from schemas import NegotiationMessage

st.set_page_config(page_title="CommerceOS", page_icon="◈", layout="wide", initial_sidebar_state="expanded")


CHAT_HEALTH_URL = "http://127.0.0.1:8765/health"
CHAT_HOST = "127.0.0.1"
CHAT_PORT = 8765


def _chat_health(timeout: float = 6) -> str | None:
    try:
        response = requests.get(CHAT_HEALTH_URL, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") == "ok":
            return None
        return f"unexpected health response: {payload}"
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
            "Port 8765 is already occupied, but the existing process is not answering "
            "the CommerceOS health check. Stop the stale process and restart Streamlit."
        )
    process = st.session_state.get("chat_server_process")
    if process is None or process.poll() is not None:
        log_dir = Path(__file__).parent
        process = subprocess.Popen(
            [sys.executable, str(log_dir / "chat_server.py")],
            cwd=Path(__file__).parent,
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
            if _chat_health() is None:
                return
            detail = stderr or health_error
            raise ChatSocketError(f"Chat service exited during startup: {detail}")
        time.sleep(0.5)
    health_error = _chat_health()
    raise ChatSocketError(
        "Chat service did not become healthy on port 8765. "
        f"Health check: {health_error or 'unknown error'}"
    )

st.markdown(
    """
    <style>
    :root { color-scheme: light; }
    .stApp, [data-testid="stAppViewContainer"] { background: #f5f7fb; color: #172033; }
    [data-testid="stHeader"] { background: rgba(245,247,251,.92); }
    [data-testid="stSidebar"] { background: #0f172a; }
    [data-testid="stSidebar"] * { color: #e2e8f0; }
    [data-testid="stSidebar"] .stCaption { color: #94a3b8 !important; }
    [data-testid="stSidebar"] [data-baseweb="radio"] label { color: #e2e8f0 !important; }
    [data-testid="stSidebar"] code { background: #1e293b; color: #bfdbfe; }
    .main .block-container { max-width: 1440px; padding-top: 2.5rem; padding-bottom: 3rem; }
    .main h1, .main h2, .main h3, .main p, .main label,
    .main [data-testid="stMetricLabel"], .main [data-testid="stMetricValue"] { color: #172033 !important; }
    .hero { background: linear-gradient(135deg,#111c38,#293f80); color:#fff; padding:28px 32px; border-radius:18px; margin-bottom:24px; box-shadow:0 12px 30px rgba(15,23,42,.12); }
    .hero h1 { margin:0; font-size:2.25rem; }
    .hero p { margin:8px 0 0; color:#cbd5e1; }
    .card { background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px; box-shadow:0 4px 18px rgba(15,23,42,.05); }
    .muted { color:#64748b; font-size:.9rem; }
    .pill { display:inline-block; padding:5px 10px; border-radius:999px; background:#dcfce7; color:#166534; font-weight:600; font-size:.8rem; }
    [data-testid="stAlert"] { border-radius:14px; }
    [data-testid="stAlert"] p, [data-testid="stAlert"] span { color:#172033 !important; }
    [data-testid="stAlert"][kind="success"] { background:#dcfce7; border:1px solid #86efac; }
    [data-testid="stAlert"][kind="info"] { background:#dbeafe; border:1px solid #93c5fd; }
    [data-testid="stAlert"][kind="error"] { background:#fee2e2; border:1px solid #fca5a5; }
    [data-testid="stAlert"][kind="warning"] { background:#fef3c7; border:1px solid #fcd34d; }
    [data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea,
    [data-testid="stNumberInput"] input { color:#172033 !important; background:#fff !important; }
    [data-testid="stMetric"] { background:#fff; border:1px solid #e2e8f0; padding:14px 16px; border-radius:14px; }
    [data-testid="stMetricLabel"] { color:#64748b !important; }
    [data-testid="stMetricValue"] { color:#172033 !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

if "result" not in st.session_state:
    st.session_state.result = None
if "transaction_machine" not in st.session_state:
    st.session_state.transaction_machine = TransactionStateMachine()
if "approval_chat_open" not in st.session_state:
    st.session_state.approval_chat_open = False
if "chat_socket_status" not in st.session_state:
    st.session_state.chat_socket_status = "not connected"
if "direct_chat_messages" not in st.session_state:
    st.session_state.direct_chat_messages = []
if "agent_chat_messages" not in st.session_state:
    st.session_state.agent_chat_messages = []
if "agent_chat_open" not in st.session_state:
    st.session_state.agent_chat_open = False
ollama = OllamaClient()
ollama_ready = ollama.is_available()

with st.sidebar:
    st.markdown("## ◈ CommerceOS")
    st.caption("Autonomous AI Commerce Network")
    page = st.radio("Workspace", ["Overview", "Buyer Request", "Seller Approval", "Direct Chat", "Seller Onboarding", "Verification"])
    st.divider()
    st.caption("LOCAL AI")
    if ollama_ready:
        st.success("Gemma 3 4B online")
    else:
        st.warning("Gemma offline • fallback mode")
    st.code("Ollama • localhost")

if page == "Overview":
    st.markdown('<div class="hero"><h1>Commerce command center</h1><p>Coordinate buyer intent, seller policies, negotiation, and agreement safety in one workspace.</p></div>', unsafe_allow_html=True)
    cols = st.columns(4)
    for col, value, label in zip(cols, ["02", "01", "00", "100%"], ["Seller agents", "Active request", "Blocked checkouts", "Policy enforcement"]):
        col.metric(label, value)
    st.subheader("Workflow health")
    cols = st.columns(3)
    cols[0].markdown('<div class="card"><span class="pill">READY</span><h3>Buyer Agent</h3><p class="muted">Natural-language intent extraction and compliant ranking.</p></div>', unsafe_allow_html=True)
    cols[1].markdown('<div class="card"><span class="pill">READY</span><h3>Seller Agents</h3><p class="muted">Independent catalogs, pricing floors, and approval policies.</p></div>', unsafe_allow_html=True)
    cols[2].markdown('<div class="card"><span class="pill">READY</span><h3>Agreement Guard</h3><p class="muted">Deterministic verification before simulated checkout.</p></div>', unsafe_allow_html=True)
    st.subheader("Demo transaction")
    st.info("Open Buyer Request to run the complete laptop example. The same workflow supports any product category with structured attributes.")

elif page == "Buyer Request":
    st.markdown('<div class="hero"><h1>Buyer request workspace</h1><p>Turn natural language into hard constraints, preferences, and a compliant negotiated offer.</p></div>', unsafe_allow_html=True)
    text = st.text_area("What are you looking for?", "Find a gaming laptop with an RTX 3050 or better, at least 16 GB RAM, under ₹70,000. Prioritize ratings and reviews.", height=120)
    if st.button("Run buyer and seller agents", type="primary", use_container_width=True):
        with st.status("Running CommerceOS agents…", expanded=True) as run_status:
            try:
                st.write("Starting secure chat service…")
                ensure_chat_server()
                st.write("Buyer Agent is extracting requirements…")
                buyer = BuyerAgent(llm=ollama if ollama_ready else None)
                request = buyer.parse_request(text)
                st.write("Supplier Agents are checking inventory and negotiating…")
                sellers = [SellerAgent(profile, llm=ollama if ollama_ready else None) for profile in demo_sellers()]
                products = {product.product_id: product for seller in sellers for product in seller.profile.products}
                result = NegotiationEngine(buyer).run(request, sellers, products)
                st.session_state.transaction_machine.transition(TransactionState.NEGOTIATING)
                st.session_state.result = (request, result, products, buyer)
                st.session_state.agent_chat_messages = []
                st.session_state.direct_chat_messages = []
                if result.chat_room_id and result.selected_offer:
                    selected_profile = next(profile for profile in demo_sellers() if profile.seller_id == result.selected_offer.seller_id)
                    try:
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
                                "supplier_id": selected_profile.seller_id,
                                "supplier_name": selected_profile.display_name,
                                "private_policies": selected_profile.policies[result.selected_offer.product_id].model_dump(),
                                "product": products[result.selected_offer.product_id].model_dump(),
                            },
                        )
                        result.direct_chat_room_id = f"{result.chat_room_id}-direct"
                        create_chat_room(
                            result.direct_chat_room_id,
                            buyer_context={"role": "buyer", "request": request.model_dump(), "budget_inr": request.max_budget_inr},
                            supplier_context={"role": "supplier human", "supplier_id": selected_profile.seller_id},
                            agent_chat_enabled=False,
                        )
                    except ChatSocketError as exc:
                        st.warning(f"Negotiation completed, but chat is unavailable: {exc}")
                run_status.update(label="Negotiation complete", state="complete", expanded=False)
            except (OllamaError, ValueError, RuntimeError) as exc:
                run_status.update(label="Workflow failed", state="error", expanded=True)
                st.error(f"CommerceOS could not complete the workflow: {exc}")
    if st.session_state.result:
        request, result, products, buyer = st.session_state.result
        st.caption(f"Requirement extraction: **{buyer.last_parse_source}**")
        if buyer.last_error:
            st.warning(f"Gemma response was rejected, so deterministic fallback was used: {buyer.last_error}")
        st.subheader("Buyer Agent interpretation")
        a, b, c = st.columns(3)
        a.metric("Category", request.product_category)
        b.metric("Quantity", request.quantity)
        c.metric("Maximum budget", f"₹{request.max_budget_inr:,}")
        st.write("**Hard constraints:**", request.hard_constraints or "None extracted")
        st.write("**Preferences:**", ", ".join(request.preferences) or "None")
        st.subheader("Supplier offers")
        st.subheader("Negotiation timeline")
        for event in result.events:
            st.write(f"• {event}")
        if result.decision_trace:
            with st.expander("Why this offer was selected"):
                for item in result.decision_trace:
                    st.write(f"✓ {item}")
        if result.supplier_chat_request and result.supplier_chat_status == "pending":
            st.subheader("Supplier direct-contact request")
            st.info(result.supplier_chat_request)
            allow, deny, message_agent = st.columns(3)
            if allow.button("Allow dedicated buyer ↔ supplier chat", type="primary", use_container_width=True):
                try:
                    if not result.direct_chat_room_id:
                        raise ChatSocketError("Dedicated direct-chat room is unavailable.")
                    set_chat_permission(result.direct_chat_room_id, True)
                    result.supplier_chat_status = "approved"
                    st.session_state.result = (request, result, products, buyer)
                    st.session_state.direct_chat_messages = []
                    st.success("Permission granted. Open Direct Chat to begin.")
                    st.rerun()
                except ChatSocketError as exc:
                    st.error(str(exc))
            if deny.button("Reject chat request", use_container_width=True):
                if result.direct_chat_room_id:
                    set_chat_permission(result.direct_chat_room_id, False)
                result.supplier_chat_status = "rejected"
                st.session_state.result = (request, result, products, buyer)
                st.rerun()
            if message_agent.button("Message supplier agent", use_container_width=True):
                st.session_state.agent_chat_open = True
                st.rerun()
        if result.chat_room_id:
            if st.button("Open supplier-agent negotiation", use_container_width=True):
                st.session_state.agent_chat_open = True
            if st.session_state.agent_chat_open:
                st.subheader("Private buyer ↔ supplier-agent chat")
                st.caption("This is the agent negotiation thread. Human-to-human chat remains locked until direct contact is accepted.")
                for item in st.session_state.agent_chat_messages:
                    role_map = {"buyer-user": ("user", "🧑"), "supplier-agent": ("assistant", "🏪")}
                    role, avatar = role_map.get(item["sender_role"], ("assistant", "⚙️"))
                    with st.chat_message(role, avatar=avatar):
                        st.write(item["message"])
                agent_message = st.chat_input("Message the supplier agent…", key="buyer_agent_chat_input")
                if agent_message:
                    try:
                        round_number = result.selected_offer.round_number if result.selected_offer else 1
                        messages = send_chat_message(
                            result.chat_room_id,
                            "buyer-user",
                            agent_message,
                            round_number,
                        )
                        st.session_state.agent_chat_messages.extend(messages)
                        st.session_state.chat_socket_status = "connected • WebSocket"
                        st.rerun()
                    except ChatSocketError as exc:
                        st.error(str(exc))
        for offer in result.offers:
            product = products[offer.product_id]
            with st.container(border=True):
                a, b, c, d = st.columns(4)
                a.write(f"**{offer.seller_id}**")
                b.metric("Price", f"₹{offer.total_price_inr:,}")
                c.metric("Rating", f"{product.rating} ★")
                d.metric("Delivery", f"{offer.delivery_days} days")
                if offer.requires_seller_approval:
                    st.warning("Seller approval required")
                else:
                    st.success("Selected compliant offer" if offer == result.selected_offer else "Offer received")
        if result.selected_offer:
            if result.selected_offer.requires_seller_approval and result.selected_offer.seller_approval_status != "approved":
                st.warning(
                    f"Seller approval required for ₹{result.selected_offer.total_price_inr:,}. "
                    "Open Seller Approval to review the negotiated terms."
                )
            else:
                st.success(f"Offer approved: ₹{result.selected_offer.total_price_inr:,}. Open Verification to record and verify the agreement.")
        else:
            st.error(result.reason)

elif page == "Seller Approval":
    st.markdown('<div class="hero"><h1>Seller approval desk</h1><p>Human approval is required when an agent negotiates below the seller automatic approval floor.</p></div>', unsafe_allow_html=True)
    if not st.session_state.result or not st.session_state.result[1].selected_offer:
        st.info("Run a buyer transaction first. Pending deals will appear here.")
    else:
        request, result, products, buyer = st.session_state.result
        offer = result.selected_offer
        seller_profile = next(profile for profile in demo_sellers() if profile.seller_id == offer.seller_id)
        product = products[offer.product_id]
        if not offer.requires_seller_approval or offer.seller_approval_status == "approved":
            st.success("No pending seller approval. This offer is already authorized.")
        else:
            policy = seller_profile.policies[offer.product_id]
            a, b, c, d = st.columns(4)
            a.metric("Negotiated price", f"₹{offer.unit_price_inr:,}")
            b.metric("Listed price", f"₹{product.listed_price_inr:,}")
            c.metric("Hard minimum", f"₹{policy.minimum_price_inr:,}")
            d.metric("Approval floor", f"₹{policy.automatic_approval_floor_inr:,}")
            st.warning(
                f"Approval required: the agent negotiated ₹{offer.unit_price_inr:,}, "
                f"below the automatic floor of ₹{policy.automatic_approval_floor_inr:,} "
                f"but above the hard minimum."
            )
            st.write(f"**Product:** {product.name}  •  **Quantity:** {offer.quantity}  •  **Delivery:** {offer.delivery_days} days")
            st.write(f"**Agent rationale:** {offer.terms.get('negotiation_note', 'Buyer requested a better trade-off.')}")
            st.info("Seller approval is handled here. Direct buyer ↔ seller chat requests and approval appear only in Buyer Request.")
            approve, reject, counter = st.columns(3)
            if approve.button("Approve deal", type="primary", use_container_width=True):
                result.selected_offer = offer.model_copy(update={"seller_approval_status": "approved"})
                result.events.append("Seller human approval granted. Agreement may proceed to buyer authorization.")
                result.messages.append(NegotiationMessage(
                    sender_id="seller-human",
                    sender_role="seller_human",
                    message="I approve the negotiated price and delivery terms. The agreement may proceed.",
                    round_number=offer.round_number,
                    message_type="approval_response",
                    related_offer_id=offer.offer_id,
                )
                )
                st.session_state.result = (request, result, products, buyer)
                st.rerun()
            if reject.button("Discuss instead", use_container_width=True):
                st.session_state.approval_chat_open = True
                st.rerun()
            with counter:
                counter_price = st.number_input("Counter price (₹)", min_value=policy.minimum_price_inr, value=offer.unit_price_inr + 1000, step=500)
                if st.button("Send counteroffer", use_container_width=True):
                    seller = SellerAgent(seller_profile, llm=ollama if ollama_ready else None)
                    response = seller.respond_to_counteroffer(request, product, counter_price, offer.round_number + 1)
                    result.selected_offer = response
                    result.offers.append(response)
                    result.events.append(f"Seller sent a human counteroffer at ₹{counter_price:,}/unit.")
                    result.messages.append(NegotiationMessage(
                        sender_id="seller-human",
                        sender_role="seller_human",
                        message=f"Human counteroffer: ₹{counter_price:,}/unit. Please confirm this revised term.",
                        round_number=response.round_number,
                        message_type="counteroffer",
                        related_offer_id=response.offer_id,
                    )
                    )
                    st.session_state.result = (request, result, products, buyer)
                    st.rerun()

elif page == "Direct Chat":
    st.markdown('<div class="hero"><h1>Dedicated buyer ↔ supplier chat</h1><p>A private, permissioned conversation powered by Gemma with isolated room history.</p></div>', unsafe_allow_html=True)
    if not st.session_state.result:
        st.info("Run a buyer transaction first.")
    else:
        request, result, products, buyer = st.session_state.result
        if result.supplier_chat_status != "approved" or not result.direct_chat_room_id:
            st.warning("The buyer has not approved a supplier direct-contact request.")
        else:
            offer = result.selected_offer
            try:
                check_chat_connection(result.direct_chat_room_id, "seller-human")
                st.session_state.chat_socket_status = "connected • WebSocket"
            except ChatSocketError as exc:
                st.session_state.chat_socket_status = f"offline • {exc}"
            st.success(f"WebSocket room: {result.direct_chat_room_id} • {st.session_state.chat_socket_status}")
            for message in st.session_state.direct_chat_messages:
                role_map = {
                    "seller-human": ("seller_human", "👤"),
                    "buyer-agent": ("buyer_agent", "🛒"),
                    "supplier-agent": ("seller_agent", "🏪"),
                    "buyer-human": ("buyer_human", "🧑"),
                }
                role, avatar = role_map.get(message["sender_role"], ("system", "⚙️"))
                with st.chat_message(role, avatar=avatar):
                    st.caption(message["sender_id"])
                    st.write(message["message"])
                    if message.get("proposal"):
                        st.caption(f"Unapplied proposal: {message['proposal']}")
            message = st.chat_input("Write to the supplier/buyer agent…", key="direct_chat_input")
            if message:
                try:
                    socket_messages = send_chat_message(
                        room_id=result.direct_chat_room_id,
                        role="seller-human",
                        message=message,
                        round_number=offer.round_number + 1,
                        context={"unit_price_inr": offer.unit_price_inr, "delivery_days": offer.delivery_days, "budget_inr": request.max_budget_inr},
                    )
                    st.session_state.direct_chat_messages.extend(socket_messages)
                    st.session_state.chat_socket_status = "connected • WebSocket"
                    st.rerun()
                except ChatSocketError as exc:
                    st.error(str(exc))
            st.divider()
            st.caption("Agent-to-agent test channel")
            agent_prompt = st.text_input("Send a message from the Supplier Agent", key="supplier_agent_prompt")
            if st.button("Run supplier ↔ buyer agent turn"):
                if not agent_prompt.strip():
                    st.warning("Enter a message first.")
                else:
                    try:
                        socket_messages = exchange_agent_message(
                            room_id=result.chat_room_id,
                            sender_role="supplier-agent",
                            message=agent_prompt,
                            round_number=offer.round_number + 1,
                        )
                        st.session_state.direct_chat_messages.extend(socket_messages)
                        st.session_state.chat_socket_status = "connected • WebSocket"
                        st.rerun()
                    except ChatSocketError as exc:
                        st.error(str(exc))
            pending_proposals = [item for item in st.session_state.direct_chat_messages if item.get("proposal")]
            if pending_proposals:
                st.subheader("Validated chat proposals")
                selected_profile = next(profile for profile in demo_sellers() if profile.seller_id == offer.seller_id)
                policy = selected_profile.policies[offer.product_id]
                product = products[offer.product_id]
                for proposal_message in pending_proposals:
                    valid, errors = validate_chat_proposal(
                        proposal_message["proposal"], request, offer, product, policy
                    )
                    if valid:
                        st.success(f"Proposal is policy-valid but not accepted: {proposal_message['proposal']}")
                        if st.button("Apply proposal for approval review", key=f"apply-{id(proposal_message)}"):
                            proposal = proposal_message["proposal"]
                            updated = offer.model_copy(update={
                                "unit_price_inr": proposal.get("unit_price_inr", offer.unit_price_inr),
                                "quantity": proposal.get("quantity", offer.quantity),
                                "total_price_inr": proposal.get("unit_price_inr", offer.unit_price_inr) * proposal.get("quantity", offer.quantity),
                                "delivery_days": proposal.get("delivery_days", offer.delivery_days),
                                "round_number": offer.round_number + 1,
                                "requires_seller_approval": True,
                                "seller_approval_status": "pending",
                            })
                            result.selected_offer = updated
                            result.offers.append(updated)
                            result.events.append("A chat proposal passed deterministic validation and entered approval review.")
                            st.session_state.result = (request, result, products, buyer)
                            st.rerun()
                    else:
                        st.error(f"Proposal rejected by policy: {', '.join(errors)}")

elif page == "Seller Onboarding":
    st.markdown('<div class="hero"><h1>Seller agent onboarding</h1><p>Configure a product, commercial limits, and an approval-safe negotiation policy.</p></div>', unsafe_allow_html=True)
    left, right = st.columns([1.2, 1])
    with left:
        name = st.text_input("Product name", "Professional Wireless Headphones")
        listed = st.number_input("Listed price (₹)", min_value=1, value=6500, step=100)
        minimum = st.number_input("Minimum acceptable price (₹)", min_value=1, value=6000, step=100)
        floor = st.number_input("Automatic approval floor (₹)", min_value=1, value=6200, step=100)
        instructions = st.text_area("Seller instructions", "Never sell below the minimum price. Negotiate politely. Confirm stock before accepting an order.")
    with right:
        st.subheader("Live policy preview")
        st.markdown(f'<div class="card"><h3>{name}</h3><p>Listed price: <b>₹{listed:,}</b></p><p>Automatic approval floor: <b>₹{floor:,}</b></p><p>Hard minimum: <b>₹{minimum:,}</b></p><hr><p class="muted">{instructions}</p></div>', unsafe_allow_html=True)
        if minimum > floor or floor > listed:
            st.error("Invalid policy: minimum price ≤ automatic approval floor ≤ listed price is required.")
        else:
            st.success("Policy is internally consistent.")

else:
    st.markdown('<div class="hero"><h1>Agreement verification guard</h1><p>Checkout is allowed only when immutable accepted terms still match current supplier terms.</p></div>', unsafe_allow_html=True)
    if not st.session_state.result or not st.session_state.result[1].selected_offer:
        st.info("Run a buyer transaction first.")
    else:
        request, result, products, _buyer = st.session_state.result
        offer = result.selected_offer
        if offer.requires_seller_approval and offer.seller_approval_status != "approved":
            st.error("Agreement cannot be recorded: seller approval is still pending.")
        else:
            agreement = record_agreement(offer)
            st.subheader("Accepted agreement")
            integrity = verify_integrity(agreement)
            st.caption(f"Agreement v{agreement.version} • SHA-256: `{agreement.integrity.sha256[:16]}...`")
            st.json(agreement.model_dump())
            st.success(
                "Agreement integrity verified — buyer authorization is still required before simulated checkout."
                if integrity.passed else "Agreement integrity check failed."
            )
            if st.button("Authorize simulated checkout", type="primary"):
                st.success("Simulated checkout authorized. No real payment was processed.")
        st.divider()
        st.subheader("Changed-price demonstration")
        changed = offer.model_copy(update={"unit_price_inr": offer.unit_price_inr + 2000, "total_price_inr": (offer.unit_price_inr + 2000) * offer.quantity})
        if not (offer.requires_seller_approval and offer.seller_approval_status != "approved"):
            verification = verify_agreement(agreement, changed)
            st.error("Checkout blocked: " + "; ".join(verification.mismatches))
            st.subheader("Autonomous recovery")
            fallback = next((candidate for candidate in result.offers if candidate.seller_id != offer.seller_id), None)
            if st.button("Block payment and recover with next supplier", type="primary"):
                recovery = RecoveryManager()
                recovered, recovered_agreement = recovery.detect_and_recover(agreement, changed, fallback)
                st.session_state.transaction_machine.transition(TransactionState.PAYMENT_BLOCKED)
                if recovered and recovered_agreement:
                    st.session_state.transaction_machine.transition(TransactionState.RECOVERED)
                    st.success("Tampering detected. Payment stayed blocked and a new agreement version was created.")
                    for action in recovery.actions:
                        st.write(f"• {action}")
                    st.json(recovered_agreement.model_dump())
