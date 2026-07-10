export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname.toLowerCase();
    const method = request.method;

    if (path === '/health') {
      return Response.json({ status: 'ok', version: '3.2.5' });
    }
    if (path === '/manual-trigger' || path === '/lucy-daily' || path === '/trigger') {
      ctx.waitUntil(runAutopilot(env));
      return Response.json({ success: true, message: 'Triggered' });
    }
    if (path === '/audit/run' && method === 'POST') return handleAudit(request, env);
    if (path === '/paypal/create-order' && method === 'POST') return handleCreateOrder(request, env);
    if (path === '/paypal/capture-order' && method === 'POST') return handleCaptureOrder(request, env);
    if (path === '/domain-search' && method === 'POST') return handleDomainSearch(request, env);
    return new Response('Not found', { status: 404 });
  }
};

async function handleAudit(request, env) {
  try {
    const body = await request.json().catch(() => ({}));
    const { store_url, email, name = 'Merchant' } = body;
    if (!store_url || !email) return Response.json({ error: 'Missing fields' }, { status: 400 });
    let merchant = await env.DB.prepare('SELECT merchant_id FROM merchants WHERE store_url = ?').bind(store_url).first();
    if (!merchant) {
      const newM = await env.DB.prepare('INSERT INTO merchants (store_url, platform) VALUES (?, ?) RETURNING merchant_id')
        .bind(store_url, 'shopify').first();
      merchant = { merchant_id: newM.merchant_id };
    }
    const tier = await env.DB.prepare('SELECT plan, full_audits_remaining FROM merchant_tiers WHERE merchant_id = ?')
      .bind(merchant.merchant_id).first() || { plan: 'free', full_audits_remaining: 0 };
    const useAdmin = tier.plan === 'pro' && tier.full_audits_remaining > 0;
    const result = await auditShopifyPublic(store_url, env, useAdmin, email, merchant.merchant_id);
    if (useAdmin) {
      await env.DB.prepare('UPDATE merchant_tiers SET full_audits_remaining = full_audits_remaining - 1 WHERE merchant_id = ?')
        .bind(merchant.merchant_id).run();
      result.fullAuditsRemaining = tier.full_audits_remaining - 1;
      await sendFullAuditEmail(email, name, store_url, result, env);
    } else {
      await sendBaitEmail(email, name, store_url, result, env);
    }
    return Response.json({ success: true, audit: result, plan: tier.plan, fullAudit: useAdmin });
  } catch (e) {
    return Response.json({ error: e.message }, { status: 500 });
  }
}

async function handleCreateOrder(request, env) {
  try {
    const { amount = '15.00', currency = 'USD' } = await request.json().catch(() => ({}));
    const auth = btoa(`${env.PAYPAL_CLIENT_ID}:${env.PAYPAL_SECRET}`);
    const tokenResp = await fetch('https://api-m.paypal.com/v1/oauth2/token', {
      method: 'POST',
      headers: { Authorization: `Basic ${auth}`, 'Content-Type': 'application/x-www-form-urlencoded' },
      body: 'grant_type=client_credentials'
    });
    if (!tokenResp.ok) throw new Error('Token failed');
    const { access_token } = await tokenResp.json();
    const orderResp = await fetch('https://api-m.paypal.com/v2/checkout/orders', {
      method: 'POST',
      headers: { Authorization: `Bearer ${access_token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ intent: 'CAPTURE', purchase_units: [{ amount: { currency_code: currency, value: amount } }] })
    });
    return Response.json(await orderResp.json(), { status: orderResp.status });
  } catch (e) {
    return Response.json({ error: e.message }, { status: 500 });
  }
}

async function handleCaptureOrder(request, env) {
  try {
    const { orderId, store_url, email } = await request.json().catch(() => ({}));
    if (!orderId || !store_url || !email) return Response.json({ error: 'Missing fields' }, { status: 400 });
    const auth = btoa(`${env.PAYPAL_CLIENT_ID}:${env.PAYPAL_SECRET}`);
    const tokenResp = await fetch('https://api-m.paypal.com/v1/oauth2/token', {
      method: 'POST',
      headers: { Authorization: `Basic ${auth}`, 'Content-Type': 'application/x-www-form-urlencoded' },
      body: 'grant_type=client_credentials'
    });
    if (!tokenResp.ok) throw new Error('Token failed');
    const { access_token } = await tokenResp.json();
    const captureResp = await fetch(`https://api-m.paypal.com/v2/checkout/orders/${orderId}/capture`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${access_token}`, 'Content-Type': 'application/json' }
    });
    const capture = await captureResp.json();
    if (!captureResp.ok) return Response.json(capture, { status: captureResp.status });
    if (capture.status === 'COMPLETED') {
      let merchant = await env.DB.prepare('SELECT merchant_id FROM merchants WHERE store_url = ?').bind(store_url).first();
      if (!merchant) {
        const newM = await env.DB.prepare('INSERT INTO merchants (store_url, platform) VALUES (?, ?) RETURNING merchant_id')
          .bind(store_url, 'shopify').first();
        merchant = { merchant_id: newM.merchant_id };
      }
      await env.DB.prepare(
        `INSERT INTO merchant_tiers (merchant_id, plan, full_audits_remaining, updated_at)
         VALUES (?, 'pro', 5, datetime('now'))
         ON CONFLICT(merchant_id) DO UPDATE SET
           plan = 'pro',
           full_audits_remaining = full_audits_remaining + 5,
           updated_at = datetime('now')`
      ).bind(merchant.merchant_id).run();
      await sendPaymentConfirmationEmail(email, store_url, env);
      return Response.json({ success: true, capture, tier: 'pro', full_audits_remaining: 5 });
    }
    return Response.json({ error: 'Capture not completed', status: capture.status }, { status: 400 });
  } catch (e) {
    return Response.json({ error: e.message }, { status: 500 });
  }
}

async function handleDomainSearch(request, env) {
  return Response.json({ error: 'Not implemented' }, { status: 501 });
}

async function sendBrevoEmail(env, toEmail, toName, subject, htmlContent) {
  if (!env.BREVO_API_KEY) return false;
  const payload = {
    sender: { name: 'Lucy™ Compliance', email: 'system@experience-lucy.online' },
    to: [{ email: toEmail, name: toName || toEmail }],
    subject,
    htmlContent
  };
  const res = await fetch('https://api.brevo.com/v3/smtp/email', {
    method: 'POST',
    headers: { 'api-key': env.BREVO_API_KEY, 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  return res.ok;
}

async function sendBaitEmail(email, name, storeUrl, audit, env) {
  const subject = `Quick Shopify Audit: ${storeUrl} - ${audit.score}/95`;
  const html = `<h2>Quick Shopify Audit: ${storeUrl}</h2><p>Hi ${name},</p><p>Your store scored <strong>${audit.score}/95</strong>.</p><ul>${audit.recommendations.map(r => `<li>${r}</li>`).join('')}</ul>`;
  await sendBrevoEmail(env, email, name, subject, html);
}

async function sendFullAuditEmail(email, name, storeUrl, audit, env) {
  const subject = `Full Compliance Report - ${storeUrl}`;
  const html = `<h2>Full Compliance Report - ${storeUrl}</h2><p>Hi ${name},</p><p>Your store scored <strong>${audit.score}/95</strong>.</p><ul>${audit.recommendations.map(r => `<li>${r}</li>`).join('')}</ul>`;
  await sendBrevoEmail(env, email, name, subject, html);
}

async function sendPaymentConfirmationEmail(email, storeUrl, env) {
  const subject = 'Payment Successful - Welcome to Pro!';
  const html = `<h2>Payment Successful - Welcome to Pro!</h2><p>You now have 5 full audits.</p>`;
  await sendBrevoEmail(env, email, null, subject, html);
}

async function auditShopifyPublic(storeUrl, env, useAdmin, email, merchant_id) {
  const prodRes = await fetch(`https://${storeUrl}/products.json?limit=50`, {
    headers: { 'User-Agent': 'Mozilla/5.0 (compatible; EnrichosBot/1.0)' }
  });
  if (!prodRes.ok) throw new Error(`Store ${storeUrl} not accessible`);
  const products = (await prodRes.json()).products || [];
  const collRes = await fetch(`https://${storeUrl}/collections.json?limit=20`, {
    headers: { 'User-Agent': 'Mozilla/5.0 (compatible; EnrichosBot/1.0)' }
  });
  const collections = collRes.ok ? ((await collRes.json()).collections || []) : [];
  const productCount = products.length;
  const collectionCount = collections.length;
  const avgDesc = products.reduce((s, p) => s + (p.body_html || '').length, 0) / (productCount || 1);
  const score = Math.min(95, Math.max(50, 60 +
    (productCount > 20 ? 15 : 0) +
    (collectionCount > 5 ? 10 : 0) +
    (avgDesc > 200 ? 10 : 0)
  ));
  const recommendations = [];
  if (productCount < 20) recommendations.push('Add more products');
  if (avgDesc < 150) recommendations.push('Improve descriptions');
  if (collectionCount < 5) recommendations.push('Create more collections');
  if (recommendations.length === 0) recommendations.push('Great foundation - upgrade for full audit');
  await env.DB.prepare(
    'INSERT INTO audit_log (merchant_id, trigger_event, gaps_detected, recommendations_generated) VALUES (?, ?, ?, ?)'
  ).bind(merchant_id, 'api', recommendations.length, recommendations.length).run();
  return {
    storeUrl,
    score,
    productCount,
    collectionCount,
    avgDescriptionLength: Math.round(avgDesc),
    orderCount: 0,
    customerCount: 0,
    recommendations,
    fullAudit: useAdmin,
    message: useAdmin ? 'Full audit complete' : 'Mini audit complete - upgrade to Pro for full audit'
  };
}

async function runAutopilot(env) {
  await env.DB.prepare("INSERT INTO audit_logs (event_type, description, created_at) VALUES (?, ?, ?)")
    .bind('autopilot', 'Cycle executed', new Date().toISOString()).run();
}
