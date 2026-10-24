import streamlit as st

from agents.buyer_agent import BuyerAgent
from agents.seller_agent import SellerAgent
from chat_client import ChatSocketError, send_seller_message
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
ollama = OllamaClient()
ollama_ready = ollama.is_available()

with st.sidebar:
    st.markdown("## ◈ CommerceOS")
    st.caption("Autonomous AI Commerce Network")
    page = st.radio("Workspace", ["Overview", "Buyer Request", "Seller Approval", "Seller Onboarding", "Verification"])
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
        buyer = BuyerAgent(llm=ollama if ollama_ready else None)
        request = buyer.parse_request(text)
        sellers = [SellerAgent(profile, llm=ollama if ollama_ready else None) for profile in demo_sellers()]
        products = {product.product_id: product for seller in sellers for product in seller.profile.products}
        result = NegotiationEngine(buyer).run(request, sellers, products)
        st.session_state.transaction_machine.transition(TransactionState.NEGOTIATING)
        st.session_state.result = (request, result, products, buyer)
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
        st.subheader("Agent negotiation chat")
        for message in result.messages:
            avatar = {"buyer_agent": "🛒", "seller_agent": "🏪", "seller_human": "👤", "system": "⚙️"}[message.sender_role]
            with st.chat_message(message.sender_role, avatar=avatar):
                st.caption(f"{message.sender_id} • Round {message.round_number} • {message.message_type.replace('_', ' ').title()}")
                st.write(message.message)
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
            if st.button("Open buyer ↔ seller negotiation chat", type="primary", use_container_width=True):
                st.session_state.approval_chat_open = True
                st.rerun()
            if st.session_state.approval_chat_open:
                st.subheader("Buyer ↔ seller live negotiation")
                st.caption(
                    f"Socket status: **{st.session_state.chat_socket_status}**. "
                    "Discuss terms before approval. Payment and agreement recording remain blocked until explicit approval."
                )
                for message in result.messages:
                    if message.sender_role in {"buyer_agent", "seller_agent", "seller_human"}:
                        avatar = {"buyer_agent": "🛒", "seller_agent": "🏪", "seller_human": "👤"}[message.sender_role]
                        with st.chat_message(message.sender_role, avatar=avatar):
                            st.caption(f"{message.sender_id} • Round {message.round_number}")
                            st.write(message.message)
                seller_message = st.chat_input(
                    "Message the Buyer Agent about price, delivery, warranty, or approval…",
                    key="approval_chat_input",
                )
                if seller_message:
                    try:
                        socket_messages = send_seller_message(
                            room_id=offer.offer_id,
                            message=seller_message,
                            round_number=offer.round_number + 1,
                            context={
                                "unit_price_inr": offer.unit_price_inr,
                                "delivery_days": offer.delivery_days,
                                "budget_inr": request.max_budget_inr,
                            },
                        )
                        for socket_message in socket_messages:
                            result.messages.append(NegotiationMessage(
                                sender_id=socket_message["sender_id"],
                                sender_role="seller_human" if socket_message["sender_role"] == "seller-human" else "buyer_agent",
                                message=socket_message["message"],
                                round_number=socket_message["round_number"],
                                message_type="request" if socket_message["sender_role"] == "seller-human" else "approval_response",
                                related_offer_id=offer.offer_id,
                            ))
                        st.session_state.chat_socket_status = "connected • WebSocket"
                    except ChatSocketError as exc:
                        st.error(str(exc))
                        st.session_state.chat_socket_status = "offline"
                    st.session_state.result = (request, result, products, buyer)
                    st.rerun()
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
                result.messages.append(NegotiationMessage(
                    sender_id="seller-human",
                    sender_role="seller_human",
                    message="I reject this negotiated offer. The deal cannot proceed.",
                    round_number=offer.round_number,
                    message_type="approval_response",
                    related_offer_id=offer.offer_id,
                )
                )
                result.selected_offer = None
                result.reason = "Seller rejected the negotiated offer."
                st.session_state.result = (request, result, products, buyer)
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
