const { Redis } = require('@upstash/redis');
const crypto = require('crypto');
const jwt = require('jsonwebtoken');

const redis = new Redis({
  url: process.env.UPSTASH_REDIS_REST_URL,
  token: process.env.UPSTASH_REDIS_REST_TOKEN,
});

const JWT_SECRET = process.env.JWT_SECRET || 'prisilblast_secret_2026';

function hashPassword(password) {
  return crypto.createHmac('sha256', 'prisilblast_salt_2026').update(password).digest('hex');
}

module.exports = async (req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });
  try {

  const { action, email, password, nama } = req.body;

  if (action === 'register') {
    if (!email || !password || !nama) return res.status(400).json({ error: 'Data tidak lengkap' });
    
    const existing = await redis.get(`pb_user:${email}`);
    if (existing) return res.status(400).json({ error: 'Email sudah terdaftar' });

    const user = {
      nama,
      email,
      password: hashPassword(password),
      plan: 'free',
      dailyLimit: 50,
      createdAt: Date.now()
    };
    await redis.set(`pb_user:${email}`, JSON.stringify(user));
    
    const token = jwt.sign({ email, nama }, JWT_SECRET, { expiresIn: '30d' });
    return res.status(200).json({ success: true, token, nama });
  }

  if (action === 'login') {
    if (!email || !password) return res.status(400).json({ error: 'Data tidak lengkap' });
    
    const raw = await redis.get(`pb_user:${email}`);
    if (!raw) return res.status(401).json({ error: 'Email tidak ditemukan' });
    
    const user = typeof raw === 'string' ? JSON.parse(raw) : raw;
    if (user.password !== hashPassword(password)) return res.status(401).json({ error: 'Password salah' });
    
    const token = jwt.sign({ email, nama: user.nama }, JWT_SECRET, { expiresIn: '30d' });
    return res.status(200).json({ success: true, token, nama: user.nama });
  }

    return res.status(400).json({ error: 'Action tidak dikenal' });
  } catch(e) {
    return res.status(500).json({ error: 'Server error: ' + e.message });
  }
};
