import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity, ArrowUpRight, Bell, Bot, CheckCircle2, ChevronRight, CircleDollarSign,
  Clock3, FileCheck2, LayoutDashboard, MessageSquare, Package, PanelLeft,
  Search, ShieldCheck, ShoppingBag, Sparkles, Store, WalletCards, XCircle
} from "lucide-react";
import "./styles.css";

const API = "http://127.0.0.1:8000";
const demoText = "Find a gaming laptop with an RTX 3050 or better, at least 16 GB RAM, under ₹70,000. Prioritize ratings and reviews.";

const nav = [
  ["Overview", LayoutDashboard, "overview"],
  ["Buyer Workspace", ShoppingBag, "buyer"],
  ["Agent Negotiations", Bot, "negotiations"],
  ["Seller Portal", Store, "seller"],
  ["Approvals", ShieldCheck, "approvals"],
  ["Conversations", MessageSquare, "conversations"],
  ["Agreements & Verification", FileCheck2, "agreements"],
  ["Transaction History", Clock3, "history"],
];

function App() {
  const [page, setPage] = useState("overview");
  const [transactions, setTransactions] = useState([]);
  const [active, setActive] = useState(null);
  const [requestText, setRequestText] = useState(demoText);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const showInfo = (message) => setNotice(message);
  const startNewRequest = () => {
    setActive(null);
    setNotice("");
    setPage("buyer");
  };
  const updateRequestText = (value) => {
    setRequestText(value);
    if (active && active.request?.original_text !== value) setActive(null);
  };

  const reload = async () => {
    const response = await fetch(`${API}/api/purchases`);
    if (!response.ok) throw new Error(`Could not load transactions (${response.status})`);
    const data = await response.json();
    setTransactions(data);
    if (active) {
      const updated = data.find((item) => item.id === active.id);
      if (updated) setActive(updated);
    }
    return data;
  };

  useEffect(() => { reload().catch(() => setNotice("Start the CommerceOS API on port 8000.")); }, []);

  const runPurchase = async () => {
    setLoading(true); setNotice("");
    try {
      const response = await fetch(`${API}/api/purchases`, {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({text: requestText}),
      });
      if (!response.ok) throw new Error((await response.json()).detail || "Purchase request failed");
      const data = await response.json();
      setActive(data); setPage("negotiations");
      await reload();
    } catch (error) { setNotice(error.message); }
    finally { setLoading(false); }
  };

  const approveChat = async (approved) => {
    if (!active) return;
    setNotice("");
    try {
      const response = await fetch(`${API}/api/purchases/${active.id}/chat-permission?approved=${approved}`, {method: "POST"});
      if (!response.ok) throw new Error((await response.json()).detail || "Chat permission update failed");
      const updated = await response.json();
      setActive(updated);
      setNotice(approved ? "Direct chat approved. Open Conversations." : "Direct chat declined.");
      await reload();
    } catch (error) { setNotice(error.message); }
  };
  const approveSeller = async (approved) => {
    if (!active) return;
    setNotice("");
    try {
      const response = await fetch(`${API}/api/purchases/${active.id}/seller-approval?approved=${approved}`, {method: "POST"});
      if (!response.ok) throw new Error((await response.json()).detail || "Seller approval update failed");
      const updated = await response.json();
      setActive(updated);
      setNotice(approved ? "Offer approved successfully." : "Offer rejected.");
      await reload();
    } catch (error) { setNotice(error.message); }
  };
  const requestChat = async () => {
    if (!active) return;
    setNotice("");
    try {
      const response = await fetch(`${API}/api/purchases/${active.id}/chat-request`, {method: "POST"});
      if (!response.ok) throw new Error((await response.json()).detail || "Direct-chat request failed");
      const updated = await response.json();
      setActive(updated);
      setNotice("Direct-chat request sent. Buyer approval is required.");
      await reload();
    } catch (error) { setNotice(error.message); }
  };

  const content = {
    overview: <Overview transactions={transactions} active={active} onStart={startNewRequest} />,
    buyer: <BuyerWorkspace value={requestText} setValue={updateRequestText} run={runPurchase} loading={loading} transaction={active} approveChat={approveChat} />,
    negotiations: <Negotiations transaction={active} />,
    seller: <SellerPortal transaction={active} requestChat={requestChat} showInfo={showInfo} />,
    approvals: <Approvals transaction={active} approve={approveSeller} showInfo={showInfo} />,
    conversations: <Conversations transaction={active} approve={approveChat} />,
    agreements: <Agreements transaction={active} showInfo={showInfo} />,
    history: <History transactions={transactions} select={(item) => {setActive(item); setPage("negotiations");}} />,
  }[page];

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><Package size={17}/></div><div><b>CommerceOS</b><small>Autonomous Commerce</small></div></div>
      <div className="nav-label">WORKSPACE</div>
      {nav.map(([label, Icon, key]) => <button key={key} onClick={() => setPage(key)} className={`nav-item ${page === key ? "active" : ""}`}><Icon size={17}/><span>{label}</span>{key === "approvals" && active?.result?.selected_offer?.requires_seller_approval && <em>1</em>}</button>)}
      <div className="sidebar-bottom"><div className="ai-status"><span className="live-dot"/> Gemma 3 4B <small>Local AI engine online</small></div><div className="profile"><div className="avatar">SA</div><div><b>Syed Aashiq</b><small>Buyer workspace</small></div></div></div>
    </aside>
    <main className="main">
      <header className="topbar"><div className="crumb"><span>CommerceOS</span><ChevronRight size={14}/><b>{nav.find((item) => item[2] === page)?.[0]}</b></div><div className="top-actions"><div className="network-status"><span className="live-dot"/> Network online <small>Gemma · 3 agents</small></div><button className="icon-btn" aria-label="Search" onClick={() => showInfo("Search will be available when transaction persistence is enabled.")}><Search size={18}/></button><button className="icon-btn" aria-label="Notifications" onClick={() => showInfo("No new notifications.")}><Bell size={18}/><i/></button><button className="create-btn" onClick={startNewRequest}><Sparkles size={16}/> Create Purchase Request</button></div></header>
      {notice && <div className="notice error">{notice}<button onClick={() => setNotice("")}>×</button></div>}
      <div className={`page-scene scene-${page}`} key={page}>{content}</div>
    </main>
  </div>;
}

function PageHeader({title, description, action}) {
  return <div className="page-header"><div><h1>{title}</h1><p>{description}</p></div>{action}</div>;
}

function Workflow({active}) { return <div className="workflow">{["Request","Negotiate","Approve","Chat","Verify"].map((step, i) => <React.Fragment key={step}><div className={`workflow-step ${step === active ? "current" : ""} ${i < ["Request","Negotiate","Approve","Chat","Verify"].indexOf(active) ? "done" : ""}`}><span>{i + 1}</span>{step}</div>{i < 4 && <div className="workflow-line"/>}</React.Fragment>)}</div>; }

function Overview({transactions, active, onStart}) {
  const offer = active?.result?.selected_offer;
  return <><div className="command-heading"><div><h1>Commerce, in motion.</h1><p>Orchestrate every request, negotiation, and agreement from one intelligent workspace.</p></div><button className="primary-btn command-cta" onClick={onStart}><Sparkles size={16}/> New procurement</button></div><div className="commerce-hero"><div className="hero-copy"><span className="hero-kicker"><span className="pulse-ring"/> Autonomous commerce network</span><h2>Turn intent into<br/><strong>an intelligent deal.</strong></h2><p>Buyer and supplier agents compare products, negotiate terms, and protect every commercial decision in real time.</p><div className="hero-actions"><button className="hero-action" onClick={onStart}>Start a procurement <ArrowUpRight size={15}/></button><span className="hero-note"><ShieldCheck size={14}/> Policy-safe by design</span></div></div><div className="commerce-illustration"><div className="visual-label label-top">Live transaction graph</div><div className="orbit orbit-one"/><div className="orbit orbit-two"/><div className="float-card card-package"><Package size={20}/><span><b>Offer matched</b><small>2.4s ago</small></span></div><div className="float-card card-agent"><Bot size={18}/><span><b>AI negotiating</b><small>Round 2 of 3</small></span></div><div className="central-box"><Package size={39}/><i/></div><div className="coin coin-one">₹</div><div className="signal-line signal-one"/><div className="signal-line signal-two"/></div><div className="hero-corner"><span>Powered by</span><b>Gemma 3 4B</b><small>Local inference</small></div></div><div className="network-ribbon"><div><span className="ribbon-icon blue"><Bot size={15}/></span><span><b>Buyer Agent</b><small>Requirements protected</small></span><strong>Active</strong></div><div><span className="ribbon-icon purple"><Store size={15}/></span><span><b>Supplier Network</b><small>Independent offers ready</small></span><strong>2 online</strong></div><div><span className="ribbon-icon green"><ShieldCheck size={15}/></span><span><b>Trust Layer</b><small>Policy enforcement enabled</small></span><strong>Secure</strong></div></div><div className="metric-grid"><Metric icon={Activity} label="Active negotiations" value={active ? "1" : "0"} tone="blue"/><Metric icon={ShieldCheck} label="Pending approvals" value={offer?.requires_seller_approval && offer.seller_approval_status !== "approved" ? "1" : "0"} tone="orange"/><Metric icon={FileCheck2} label="Awaiting verification" value={offer ? "1" : "0"} tone="purple"/><Metric icon={CheckCircle2} label="Completed" value={transactions.filter((x) => x.result?.selected_offer).length} tone="green"/></div><Workflow active={active ? "Negotiate" : "Request"}/><div className="dashboard-grid"><section className="panel"><PanelTitle icon={Activity} title="Recent activity" action="Live"/>{active ? active.result.events.slice(-5).reverse().map((event, i) => <div className="activity" key={i}><span className="activity-dot"/><div><b>{event}</b><small>CommerceOS transaction activity</small></div><ArrowUpRight size={15}/></div>) : <Empty icon={Bot} text="Start a purchase request to see live agent activity."/>}</section><section className="panel"><PanelTitle icon={Package} title="Active transaction"/>{offer ? <TransactionCard offer={offer} onClick={onStart}/> : <Empty icon={ShoppingBag} text="No active transaction yet."/>}</section></div></>;
}

function BuyerWorkspace({value, setValue, run, loading, transaction, approveChat}) {
  const request = transaction?.result?.supplier_chat_request;
  const pending = transaction?.result?.supplier_chat_status === "pending" && request;
  return <><PageHeader eyebrow="BUYER WORKSPACE" title="Create Purchase Request" description="Describe intent once. Watch Gemma convert it into a safe, negotiable commercial brief."/><Workflow active="Request"/><div className="workspace-grid"><section className="panel form-panel intent-panel"><div className="panel-heading"><div className="panel-icon blue"><ShoppingBag size={18}/></div><div><h2>Purchase requirements</h2><p>Natural language is enough. The Buyer Agent extracts the details.</p></div></div><label>What are you looking for?</label><textarea value={value} onChange={(e) => setValue(e.target.value)} rows="6"/><div className="helper"><Sparkles size={15}/> Try: “100 laptops under ₹70,000 with delivery by Friday”</div><IntentPreview value={value}/><button className="primary-btn wide" onClick={run} disabled={loading}>{loading ? <><span className="spinner"/> Agents are mapping the market…</> : <><Sparkles size={16}/> Start Autonomous Procurement</>}</button>{pending && <div className="chat-request-card"><span className="status orange">Supplier requests direct chat</span><h3>Clarification needed before final approval</h3><p>{request}</p><div className="approval-actions"><button className="primary-btn" onClick={() => approveChat(true)}>Accept Chat Request</button><button className="secondary-btn" onClick={() => approveChat(false)}>Decline</button></div></div>}</section><aside className="side-panel journey-panel"><div className="side-title">The request becomes a deal</div><div className="journey-line">{["Intent captured","Suppliers matched","Terms negotiated","Agreement protected"].map((x, i) => <div className="journey-node" key={x}><span>{String(i + 1).padStart(2, "0")}</span><div><b>{x}</b><small>{["Gemma extracts constraints","Private catalogs stay isolated","Counteroffers stay bounded","Hash blocks changed terms"][i]}</small></div></div>)}</div><div className="constraint-box"><b>Your constraints are protected</b><p><ShieldCheck size={14}/> Budget and hard requirements</p><p><ShieldCheck size={14}/> Seller minimum prices</p><p><ShieldCheck size={14}/> Agreement verification</p></div></aside></div></>; }

function IntentPreview({value}) {
  const lower = value.toLowerCase();
  const budget = lower.match(/(?:under|below|max(?:imum)?|budget)[^\d₹]*(?:₹|rs\.?|inr)?\s*([\d,]+)\s*(k|thousand|lakh|lakhs)?/);
  const amount = budget ? `${Number(budget[1].replace(/,/g, "")) * (budget[2] === "k" || budget[2] === "thousand" ? 1000 : budget[2] === "lakh" || budget[2] === "lakhs" ? 100000 : 1)}` : null;
  const category = lower.split(/\b(?:under|below|max(?:imum)?|budget)\b/)[0].replace(/^(i need|find|buy|please get|a|an)\s+/i, "").trim() || "product category";
  const chips = [
    ["INTENT", category],
    ["BUDGET", amount ? `₹${Number(amount).toLocaleString("en-IN")}` : "Waiting for a limit"],
    ["MODE", "Gemma + policy layer"],
  ];
  return <div className="intent-preview"><div className="intent-preview-head"><span><span className="scan-dot"/> LIVE INTERPRETATION</span><small>updates as you type</small></div><div className="intent-chips">{chips.map(([label, text]) => <div className="intent-chip" key={label}><small>{label}</small><b>{text}</b></div>)}</div></div>;
}

function Negotiations({transaction}) {
  const result = transaction?.result;
  const [filter, setFilter] = React.useState("all");
  const [visibleCount, setVisibleCount] = React.useState(0);
  const [selectedMessage, setSelectedMessage] = React.useState(null);
  React.useEffect(() => {
    const messages = result?.messages || [];
    setVisibleCount(messages.length);
    setSelectedMessage(messages[messages.length - 1] || null);
  }, [transaction?.id, result?.messages?.length]);
  if (!result) return <EmptyPage title="Agent Negotiations" text="Create a purchase request to start the negotiation."/>;
  const filteredMessages = result.messages.filter((message) => {
    if (filter === "all") return true;
    if (filter === "offers") return ["offer", "counteroffer", "concession", "acceptance"].includes(message.message_type);
    if (filter === "decisions") return ["selection", "rejection", "acceptance", "approval_request"].includes(message.message_type);
    return message.sender_role === filter;
  });
  const shownMessages = filteredMessages.slice(0, visibleCount);
  const nodes = [
    ["request", "Buyer Request", "request", "Captured"],
    ["buyer", "Buyer Agent", "buyer", `${result.messages.filter((m) => m.sender_role === "buyer_agent").length} messages`],
    ["coordinator", "Super Agent", "coordinator", `Round ${result.current_round || 1}`],
    ["nova", "Nova Agent", "supplier", offerState(result, "seller-nova")],
    ["orbit", "Orbit Agent", "supplier", offerState(result, "seller-orbit")],
    ["evaluate", "Offer Evaluation", "evaluate", `${result.offers.length} packages`],
    ["validate", "Policy Validation", "validate", result.selected_offer ? "Passed" : "Waiting"],
    ["verify", "Agreement Verify", "verify", result.selected_offer ? "Ready" : "Blocked"],
  ];
  return <><PageHeader eyebrow="LIVE NEGOTIATION GRAPH" title="Agents are making a deal." description="Every node below is backed by the recorded negotiation messages, offers, and policy checks."/><Workflow active="Negotiate"/><div className="transaction-banner"><div className="product-orb"><Package/></div><div><div className="transaction-round">Round {result.current_round || 1}</div><h2>{result.selected_offer?.product_id || transaction.request.product_category}</h2><p>{transaction.id.slice(0, 8)} · {result.messages.length} recorded messages · {result.offers.length} offer packages</p></div><div className="banner-stat"><small>Buyer budget</small><b>₹{transaction.request.max_budget_inr.toLocaleString()}</b></div><div className="banner-stat"><small>Outcome</small><strong className={`status ${result.selected_offer ? "green" : "orange"}`}>{result.selected_offer ? "Best package found" : "No compliant offer"}</strong></div></div><WorkflowGraph result={result}/><div className="negotiation-stage legacy-workflow"><div className="stage-topline"><span><span className="pulse-ring"/> LIVE EVENT GRAPH</span><small>Click a node to inspect its role and evidence</small></div><div className="workflow-canvas">{nodes.map((node, index) => <React.Fragment key={node[0]}><div className={`agent-node node-${node[2]} ${index < 6 ? "node-active" : ""}`}><div className="node-port"/><div className="node-icon">{node[2] === "buyer" ? <ShoppingBag size={16}/> : node[2] === "supplier" ? <Store size={16}/> : node[2] === "validate" || node[2] === "verify" ? <ShieldCheck size={16}/> : node[2] === "evaluate" ? <CircleDollarSign size={16}/> : <Bot size={16}/>}</div><div><small>{node[2].toUpperCase()}</small><b>{node[1]}</b><span>{node[3]}</span></div><i className="node-pulse"/></div>{index < nodes.length - 1 && <div className="graph-edge"><span/></div>}</React.Fragment>)}</div></div><div className="content-grid negotiation-content"><section className="panel"><PanelTitle icon={Activity} title="Negotiation timeline" action={`${shownMessages.length}/${filteredMessages.length} events`}/><div className="timeline-filter">{[["all", "All events"], ["offers", "Offers"], ["decisions", "Decisions"], ["buyer_agent", "Buyer"], ["seller_agent", "Suppliers"]].map(([value, label]) => <button key={value} className={filter === value ? "filter-active" : ""} onClick={() => {setFilter(value); setVisibleCount(result.messages.length);}}>{label}</button>)}</div>{shownMessages.map((message, i) => <button className={`timeline-item timeline-button ${selectedMessage === message ? "selected" : ""}`} key={`${message.related_offer_id || "event"}-${i}`} onClick={() => setSelectedMessage(message)}><div className={`timeline-icon ${message.sender_role === "buyer_agent" ? "blue" : message.sender_role === "seller_agent" ? "purple" : "gray"}`}>{message.sender_role === "buyer_agent" ? <ShoppingBag size={15}/> : message.sender_role === "seller_agent" ? <Store size={15}/> : <Activity size={15}/>}</div><div className="timeline-body"><div><b>{message.sender_id}</b><span>to {message.recipient_id || "network"} · Round {message.round_number}</span></div><p>{message.message}</p>  <div className="message-meta"><span>{message.message_type}</span>{message.generated_by === "gemma" ? <span className="generation-badge verified">Gemma · Ollama verified</span> : <span className="generation-badge">{message.generated_by || "system"}</span>}{message.validation_status !== "not_checked" && <span className={`validation-${message.validation_status}`}>{message.validation_status}</span>}{message.proposal?.unit_price_inr && <strong>₹{Number(message.proposal.unit_price_inr).toLocaleString()} / unit</strong>}</div></div></button>)}{shownMessages.length < filteredMessages.length && <button className="secondary-btn timeline-more" onClick={() => setVisibleCount((count) => count + 5)}>Load more conversation</button>}</section><section className="panel offer-panel"><PanelTitle icon={CircleDollarSign} title="Conversation detail" action={selectedMessage ? `Round ${selectedMessage.round_number}` : "Waiting"}/>{selectedMessage ? <div className="message-detail"><span className={`status ${selectedMessage.validation_status === "invalid" ? "red" : "green"}`}>{selectedMessage.message_type}</span><h3>{selectedMessage.sender_id} → {selectedMessage.recipient_id || "network"}</h3>  <p>{selectedMessage.rationale || "Recorded negotiation event."}</p><div className="generation-audit"><b>{selectedMessage.generated_by === "gemma" ? "Gemma-generated decision" : "Deterministic/system event"}</b>{selectedMessage.model && <span>Model: {selectedMessage.model}</span>}{selectedMessage.ollama_request_id && <span>Ollama request: {selectedMessage.ollama_request_id}</span>}{selectedMessage.prompt_hash && <span>Prompt SHA-256: {selectedMessage.prompt_hash.slice(0, 16)}…</span>}{selectedMessage.response_hash && <span>Response SHA-256: {selectedMessage.response_hash.slice(0, 16)}…</span>}{selectedMessage.generation_status === "verified" && <span className="audit-ok">Live model response recorded</span>}</div>{selectedMessage.proposal && <div className="proposal-grid">{Object.entries(selectedMessage.proposal).filter(([, value]) => value !== undefined && typeof value !== "object").map(([key, value]) => <div key={key}><small>{key.replaceAll("_", " ")}</small><b>{typeof value === "number" && key.includes("price") ? `₹${value.toLocaleString()}` : String(value)}</b></div>)}</div>}{selectedMessage.changed_terms?.length > 0 && <div className="changed-terms">Changed: {selectedMessage.changed_terms.join(", ")}</div>}</div> : <div className="empty"><Activity size={26}/><p>No conversation event selected.</p></div>}{result.selected_offer && <><PanelTitle icon={CircleDollarSign} title="Final package"/><TransactionCard offer={result.selected_offer}/></>}<div className="decision-box"><b>Decision evidence</b>{result.decision_trace.map((x) => <p key={x}><CheckCircle2 size={14}/>{x}</p>)}<p><Activity size={14}/> {result.termination_reason}</p></div></section></div></>;
}

function offerState(result, sellerId) {
  const offers = result.offers.filter((offer) => offer.seller_id === sellerId);
  const latest = offers[offers.length - 1];
  return latest ? `₹${latest.unit_price_inr.toLocaleString()} · R${latest.round_number}` : "No viable package";
}

function WorkflowGraph({result}) {
  const count = (predicate) => result.messages.filter(predicate).length;
  const node = (id, title, role, detail, Icon, status = "done") => (
    <div className={`graph-node graph-${role} graph-${status}`} key={id}>
      <div className="graph-node-icon"><Icon size={17}/></div>
      <div className="graph-node-copy"><small>{role}</small><b>{title}</b><span>{detail}</span></div>
      <i>{status === "done" ? "✓" : status === "waiting" ? "…" : "!"}</i>
    </div>
  );
  return <section className="layered-workflow">
    <div className="workflow-head"><div><b>Negotiation workflow</b><span>Follow the deal from intent to verified checkout.</span></div><strong>{result.messages.length} events · {result.current_round || 1} rounds</strong></div>
    <div className="workflow-map">
      <div className="workflow-row workflow-entry">{node("request", "Buyer request", "input", "Requirements captured", Package)}<span className="flow-arrow">↓</span>{node("buyer", "Buyer Agent", "agent", `${count((m) => m.sender_role === "buyer_agent")} messages`, ShoppingBag)}<span className="flow-arrow">→</span>{node("coordinator", "Super Agent", "coordinator", `Round ${result.current_round || 1} active`, Bot)}</div>
      <div className="branch-line"><span/><span/><span/></div>
      <div className="workflow-row supplier-row">{node("nova", "Nova Electronics", "supplier", offerState(result, "seller-nova"), Store)}{node("orbit", "Orbit Digital", "supplier", offerState(result, "seller-orbit"), Store)}<div className="branch-label">Independent supplier branches<br/><small>Private policy · stock · delivery</small></div></div>
      <div className="workflow-row workflow-process"><span className="flow-arrow">↓</span>{node("engine", "Negotiation engine", "engine", `${count((m) => m.message_type === "counteroffer")} counteroffers`, MessageSquare)}<span className="flow-arrow">→</span>{node("evaluation", "Offer evaluation", "evaluation", `${result.offers.length} packages compared`, CircleDollarSign)}<span className="flow-arrow">→</span>{node("check", "Constraint check", "check", result.selected_offer ? "Budget and policy passed" : "No valid package", ShieldCheck, result.selected_offer ? "done" : "waiting")}</div>
      <div className="workflow-row workflow-finish">{node("approval", "Seller approval", "approval", result.selected_offer?.requires_seller_approval ? "Human decision required" : "Delegated authority", ShieldCheck, result.selected_offer?.requires_seller_approval ? "waiting" : "done")}<span className="flow-arrow">→</span>{node("agreement", "Agreement record", "agreement", result.selected_offer ? "Terms locked and hashed" : "Waiting for selection", FileCheck2, result.selected_offer ? "done" : "waiting")}<span className="flow-arrow">→</span>{node("checkout", "Verified checkout", "checkout", result.selected_offer ? "Authorization gate" : "Blocked", WalletCards, result.selected_offer ? "waiting" : "blocked")}</div>
    </div>
    <div className="workflow-legend"><span><i className="legend-dot live"/> Active evidence</span><span><i className="legend-dot branch"/> Supplier branch</span><span><i className="legend-dot blocked"/> Blocked until approval</span></div>
  </section>;
}

function SellerPortal({transaction, requestChat, showInfo}) { const offer = transaction?.result?.selected_offer; const approvalStatus = offer?.seller_approval_status; return <><PageHeader eyebrow="SELLER PORTAL" title="Supplier operations" description="Catalog, policies, active negotiations, and buyer contact requests in one place." action={<button className="secondary-btn" onClick={() => showInfo("Product catalog editing is outside this demo workspace.")}><Package size={16}/> Add Product</button>}/><div className="seller-tabs"><b>Active Negotiations</b><span>Products & Inventory</span><span>Approval Settings</span><span>Analytics</span></div>{offer ? <section className="panel table-panel"><PanelTitle icon={Store} title="Active negotiations" action="1 live"/><div className="data-row header"><span>Product</span><span>Buyer</span><span>Current offer</span><span>Delivery</span><span>Status</span><span>Action</span></div><div className="data-row"><span><b>{offer.product_id}</b><small>RTX gaming laptop</small></span><span>Syed Aashiq<small>{transaction.id.slice(0,8)}</small></span><span><b>₹{offer.total_price_inr.toLocaleString()}</b></span><span>{offer.delivery_days} days</span><span><strong className={`status ${approvalStatus === "approved" ? "green" : approvalStatus === "rejected" ? "red" : "orange"}`}>{approvalStatus === "approved" ? "Approved" : approvalStatus === "rejected" ? "Rejected" : "Approval required"}</strong></span><button className="link-btn" onClick={requestChat}>Request Direct Chat</button></div></section> : <EmptyPage title="Seller Portal" text="No active negotiation. Create a buyer request first."/>}</>; }

function Approvals({transaction, approve, showInfo}) { const offer = transaction?.result?.selected_offer; const pending = offer?.requires_seller_approval && offer.seller_approval_status !== "approved"; return <><PageHeader eyebrow="CONTROL CENTER" title="Pending Approvals" description="Commercial actions that require a human decision."/><Workflow active="Approve"/>{pending ? <section className="approval-card"><div className="approval-head"><div className="alert-icon"><ShieldCheck/></div><div><span className="status orange">Seller approval required</span><h2>Negotiated offer below automatic authority</h2><p>Supplier Agent negotiated a price that requires seller confirmation.</p></div></div><div className="approval-details"><Detail label="Supplier" value={offer.seller_id}/><Detail label="Offer" value={`₹${offer.unit_price_inr.toLocaleString()} / unit`}/><Detail label="Total" value={`₹${offer.total_price_inr.toLocaleString()}`}/><Detail label="Delivery" value={`${offer.delivery_days} days`}/></div><div className="approval-actions"><button className="primary-btn" onClick={() => approve(true)}>Approve offer</button><button className="secondary-btn" onClick={() => approve(false)}>Reject</button><button className="ghost-btn" onClick={() => showInfo("Counteroffers are handled by the Buyer Agent during bounded negotiation.")}>Counteroffer</button></div></section> : <EmptyPage title="No pending approvals" text="Everything is within delegated authority."/>}</>; }

function Conversations({transaction}) {
  const approved = transaction?.result?.supplier_chat_status === "approved";
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState("");
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    if (!approved || !transaction?.result?.direct_chat_room_id) return undefined;
    const socket = new WebSocket(`ws://127.0.0.1:8765/ws/${transaction.result.direct_chat_room_id}/buyer-human`);
    socket.onopen = () => setConnected(true);
    socket.onclose = () => setConnected(false);
    socket.onmessage = (event) => {
      const payload = JSON.parse(event.data);
      if (payload.type === "message") setMessages((current) => [...current, payload]);
    };
    return () => socket.close();
  }, [approved, transaction?.result?.direct_chat_room_id]);
  const send = () => {
    if (!text.trim() || !transaction?.result?.direct_chat_room_id) return;
    const socket = new WebSocket(`ws://127.0.0.1:8765/ws/${transaction.result.direct_chat_room_id}/buyer-human`);
    socket.onopen = () => {
      socket.send(JSON.stringify({type: "message", message: text, round_number: transaction.result.selected_offer?.round_number || 1}));
      setText("");
      setTimeout(() => socket.close(), 1000);
    };
  };
  return <><PageHeader eyebrow="SECURE MESSAGING" title="Conversations" description="Permissioned direct communication, separate from autonomous AI negotiation."/><Workflow active="Chat"/>{approved ? <section className="chat-layout"><aside className="conversation-list"><div className="search-box"><Search size={15}/> Search conversations</div><div className="conversation active"><div className="avatar purple">N</div><div><b>{transaction.result.selected_offer?.seller_id || "Supplier"}</b><small>Direct buyer conversation</small></div><span className={`status ${connected ? "green" : "orange"}`}>{connected ? "Live" : "Offline"}</span></div></aside><section className="chat-window"><div className="chat-header"><div className="avatar purple">N</div><div><b>{transaction.result.selected_offer?.seller_id || "Supplier"}</b><small>Direct chat approved · Transaction {transaction.id.slice(0,8)}</small></div><ShieldCheck size={18} className="secure"/></div><div className="messages"><div className="system-message">Direct chat approved by buyer. Commercial terms remain protected.</div>{messages.map((message, index) => <div className={`message ${message.sender_role === "buyer-human" ? "sent" : "received"}`} key={`${index}-${message.message}`}><small>{message.sender_role.replace("-", " ")}</small><p>{message.message}</p></div>)}</div><div className="composer"><input value={text} onChange={(event) => setText(event.target.value)} onKeyDown={(event) => event.key === "Enter" && send()} placeholder="Write a message…"/><button className="primary-btn" onClick={send}>Send</button></div></section></section> : <EmptyPage title="No direct conversation open" text="A buyer must accept a supplier's chat request before this workspace opens."/>}</>;
}

function Agreements({transaction, showInfo}) { return <><PageHeader eyebrow="TRUST & SAFETY" title="Agreements & Verification" description="Accepted terms are hashed, versioned, and checked before simulated checkout."/><Workflow active="Verify"/>{transaction ? <div className="content-grid"><section className="panel"><PanelTitle icon={FileCheck2} title="Agreement details" action="Integrity verified"/><div className="agreement-grid"><Detail label="Product" value={transaction.result.selected_offer?.product_id || "—"}/><Detail label="Supplier" value={transaction.result.selected_offer?.seller_id || "—"}/><Detail label="Quantity" value={transaction.result.selected_offer?.quantity || "—"}/><Detail label="Delivery" value={`${transaction.result.selected_offer?.delivery_days || "—"} days`}/></div><div className="hash"><ShieldCheck size={17}/><div><b>SHA-256 integrity hash</b><code>Agreement terms are tamper-evident</code></div></div><button className="primary-btn wide" onClick={() => showInfo("Checkout is simulated and remains blocked until agreement authorization is implemented.")}>Authorize simulated checkout</button></section><section className="panel"><PanelTitle icon={ShieldCheck} title="Verification guard"/><div className="check-row"><CheckCircle2/> Price matches agreement <b>Passed</b></div><div className="check-row"><CheckCircle2/> Quantity matches agreement <b>Passed</b></div><div className="check-row"><CheckCircle2/> Delivery terms match <b>Passed</b></div><div className="blocked-box"><WalletCards size={18}/><div><b>Payment authorization protected</b><p>Checkout remains blocked until buyer approval and verification succeed.</p></div></div></section></div> : <EmptyPage title="No agreement yet" text="Complete a procurement request to create an agreement."/>}</>; }

function History({transactions, select}) { return <><PageHeader eyebrow="AUDIT TRAIL" title="Transaction History" description="Every procurement decision, approval, and recovery action remains traceable."/><section className="panel table-panel"><PanelTitle icon={Clock3} title="All transactions" action={`${transactions.length} record(s)`}/>{transactions.length ? transactions.map((item) => <button className="history-row" key={item.id} onClick={() => select(item)}><span className="history-id">{item.id.slice(0,8)}</span><span>{item.result?.selected_offer?.product_id || "Purchase request"}</span><span>{item.result?.selected_offer?.seller_id || "—"}</span><span>₹{(item.result?.selected_offer?.total_price_inr || 0).toLocaleString()}</span><strong className="status green">Active</strong><ChevronRight size={16}/></button>) : <Empty icon={Clock3} text="No transactions yet."/>}</section></>; }

function Metric({icon: Icon, label, value, tone}) { return <div className="metric-card"><div className={`metric-icon ${tone}`}><Icon size={18}/></div><div><small>{label}</small><b>{value}</b><span>Live application state</span></div></div>; }
function PanelTitle({icon: Icon, title, action}) { return <div className="panel-title"><div><Icon size={17}/><h2>{title}</h2></div>{action && <span className="panel-action">{action}</span>}</div>; }
function TransactionCard({offer, onClick}) { return <div className="transaction-card" onClick={onClick}><div className="product-thumb"><Package size={26}/></div><div className="transaction-main"><b>{offer.product_id}</b><small>{offer.seller_id} · {offer.quantity} unit</small></div><div><small>Total</small><b>₹{offer.total_price_inr.toLocaleString()}</b></div><div><small>Delivery</small><b>{offer.delivery_days} days</b></div><span className="status orange">Review</span></div>; }
function Detail({label, value}) { return <div className="detail"><small>{label}</small><b>{value}</b></div>; }
function Empty({icon: Icon, text}) { return <div className="empty"><Icon size={26}/><p>{text}</p></div>; }
function EmptyPage({title, text}) { return <><PageHeader eyebrow="COMMERCEOS" title={title} description={text}/><div className="empty-page"><Bot size={38}/><h2>{title}</h2><p>{text}</p></div></>; }

createRoot(document.getElementById("root")).render(<App />);
