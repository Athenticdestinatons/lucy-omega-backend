const express = require('express');
const cors = require('cors');
const fs = require('fs').promises;
const path = require('path');
const fetch = require('node-fetch');

const app = express();
app.use(cors());
app.use(express.json());

const DATA_DIR = './data';
const INFLUENCERS_FILE = path.join(DATA_DIR, 'influencers.json');
const STATS_FILE = path.join(DATA_DIR, 'stats.json');
const CLICKS_FILE = path.join(DATA_DIR, 'clicks.json');

async function initData() {
  await fs.mkdir(DATA_DIR, { recursive: true });
  try { await fs.access(INFLUENCERS_FILE); } catch(e) { await fs.writeFile(INFLUENCERS_FILE, '[]'); }
  try { await fs.access(STATS_FILE); } catch(e) { await fs.writeFile(STATS_FILE, '{}'); }
  try { await fs.access(CLICKS_FILE); } catch(e) { await fs.writeFile(CLICKS_FILE, '[]'); }
}
initData();

async function readJSON(file) {
  const data = await fs.readFile(file, 'utf8');
  return JSON.parse(data);
}
async function writeJSON(file, data) {
  await fs.writeFile(file, JSON.stringify(data, null, 2));
}

async function ensureStats(username) {
  const stats = await readJSON(STATS_FILE);
  if (!stats[username]) stats[username] = { clicks: 0, conversions: 0, commission_estimate: 0 };
  await writeJSON(STATS_FILE, stats);
}

const AI_PROVIDER = process.env.AI_PROVIDER || 'deepseek';
const DEEPSEEK_API_KEY = process.env.DEEPSEEK_API_KEY;
const GROQ_API_KEY = process.env.GROQ_API_KEY;

async function callAI(prompt, temperature = 0.2, maxTokens = 300) {
  let url, headers, body;
  if (AI_PROVIDER === 'groq') {
    if (!GROQ_API_KEY) throw new Error('GROQ_API_KEY missing');
    url = 'https://api.groq.com/openai/v1/chat/completions';
    headers = { 'Authorization': `Bearer ${GROQ_API_KEY}`, 'Content-Type': 'application/json' };
    body = {
      model: 'mixtral-8x7b-32768',
      messages: [{ role: 'user', content: prompt }],
      temperature,
      max_tokens: maxTokens
    };
  } else {
    if (!DEEPSEEK_API_KEY) throw new Error('DEEPSEEK_API_KEY missing');
    url = 'https://api.deepseek.com/v1/chat/completions';
    headers = { 'Authorization': `Bearer ${DEEPSEEK_API_KEY}`, 'Content-Type': 'application/json' };
    body = {
      model: 'deepseek-chat',
      messages: [{ role: 'user', content: prompt }],
      temperature,
      max_tokens: maxTokens
    };
  }
  const response = await fetch(url, { method: 'POST', headers, body: JSON.stringify(body) });
  const data = await response.json();
  return data.choices[0].message.content;
}

app.post('/api/signup', async (req, res) => {
  const { username, name, email, social_link, followers, niche, platform } = req.body;
  if (!username || !email) return res.status(400).json({ error: 'Missing username or email' });
  
  const influencers = await readJSON(INFLUENCERS_FILE);
  if (influencers.find(i => i.username === username)) {
    return res.status(409).json({ error: 'Username already exists' });
  }
  const newInfluencer = {
    username, name, email, social_link, followers: followers || 0, niche, platform,
    status: 'pending', spam_score: null, created_at: new Date().toISOString()
  };
  influencers.push(newInfluencer);
  await writeJSON(INFLUENCERS_FILE, influencers);
  await ensureStats(username);
  verifyWithAI(username, social_link, niche).catch(console.error);
  res.json({ success: true, status: 'pending', message: `Verification started using ${AI_PROVIDER}` });
});

async function verifyWithAI(username, socialLink, niche) {
  const prompt = `You are an influencer verification system. Evaluate this profile:
Username: ${username}
Social link: ${socialLink || 'not provided'}
Niche: ${niche || 'not specified'}
Return ONLY valid JSON with no extra text: { "legit": true/false, "spam_score": 0.0-1.0, "reason": "short" }`;
  try {
    const resultText = await callAI(prompt, 0.2, 300);
    const result = JSON.parse(resultText);
    const finalStatus = result.legit ? (result.spam_score < 0.3 ? 'approved' : 'pending_review') : 'rejected';
    const influencers = await readJSON(INFLUENCERS_FILE);
    const idx = influencers.findIndex(i => i.username === username);
    if (idx !== -1) {
      influencers[idx].status = finalStatus;
      influencers[idx].spam_score = result.spam_score;
      await writeJSON(INFLUENCERS_FILE, influencers);
    }
  } catch (err) {
    console.error(`${AI_PROVIDER} verification failed:`, err);
    const influencers = await readJSON(INFLUENCERS_FILE);
    const idx = influencers.findIndex(i => i.username === username);
    if (idx !== -1) {
      influencers[idx].status = 'pending_review';
      await writeJSON(INFLUENCERS_FILE, influencers);
    }
  }
}

app.get('/api/influencer/:username', async (req, res) => {
  const influencers = await readJSON(INFLUENCERS_FILE);
  const user = influencers.find(i => i.username === req.params.username);
  if (!user) return res.status(404).json({ error: 'Not found' });
  if (user.status !== 'approved') return res.status(403).json({ error: 'Not yet approved' });
  res.json({ username: user.username, name: user.name, status: user.status, niche: user.niche, platform: user.platform });
});

app.post('/api/track-click', async (req, res) => {
  const { referrer_username, referred_email } = req.body;
  if (!referrer_username) return res.status(400).json({ error: 'Missing referrer' });
  const stats = await readJSON(STATS_FILE);
  if (!stats[referrer_username]) stats[referrer_username] = { clicks: 0, conversions: 0, commission_estimate: 0 };
  stats[referrer_username].clicks++;
  await writeJSON(STATS_FILE, stats);
  const clicks = await readJSON(CLICKS_FILE);
  clicks.push({ referrer_username, referred_email: referred_email || null, clicked_at: new Date().toISOString() });
  await writeJSON(CLICKS_FILE, clicks);
  res.json({ success: true });
});

app.get('/api/dashboard/:username', async (req, res) => {
  const influencers = await readJSON(INFLUENCERS_FILE);
  const user = influencers.find(i => i.username === req.params.username);
  if (!user) return res.status(404).json({ error: 'User not found' });
  const stats = await readJSON(STATS_FILE);
  const userStats = stats[req.params.username] || { clicks: 0, conversions: 0, commission_estimate: 0 };
  res.json({ username: req.params.username, status: user.status, ...userStats });
});

app.post('/api/conversion', async (req, res) => {
  const { referrer_username } = req.body;
  if (!referrer_username) return res.status(400).json({ error: 'Missing referrer' });
  const stats = await readJSON(STATS_FILE);
  if (!stats[referrer_username]) stats[referrer_username] = { clicks: 0, conversions: 0, commission_estimate: 0 };
  stats[referrer_username].conversions++;
  stats[referrer_username].commission_estimate += 10;
  await writeJSON(STATS_FILE, stats);
  res.json({ success: true });
});

const PORT = process.env.PORT || 3000;
// AI Tool endpoint (8 tools)
app.post("/api/ai-tool", async (req, res) => {
  const { tool, prompt } = req.body;
  const prompts = {
    chat: "You are Lucy, an AI assistant for creators. Answer concisely and helpfully: ",
    headline: "Generate 10 unique, click‑worthy headlines for: ",
    email: "Write a short persuasive marketing email (max 200 words) for: ",
    youtube_title: "Generate 10 high‑CTR YouTube titles for: ",
    script: "Write a 60‑90 second video script for: ",
    landing_page: "Generate landing page copy (headline, subheadline, 3 benefits, CTA) for: ",
    ad_copy: "Write 3 short ad copies (max 90 chars each) for: ",
    affiliate_promo: "Write affiliate promotion (email, tweet, post) for: ",
    review_writer: "Write a 300‑word affiliate review article for: "
  };
  const system = prompts[tool];
  if (!system) return res.status(400).json({ error: "Unknown tool" });
  try {
    const result = await callAI(system + prompt, 0.7, 800);
    res.json({ result });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.listen(PORT, () => console.log(`Backend running on port ${PORT} using AI provider: ${AI_PROVIDER}`));
