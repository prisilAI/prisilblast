const { Redis } = require('@upstash/redis');

const redis = new Redis({
  url: process.env.UPSTASH_REDIS_REST_URL,
  token: process.env.UPSTASH_REDIS_REST_TOKEN,
});

module.exports = async (req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  try {
    const { email, plan, ref } = req.body;
    if (!email || !plan || !ref) return res.status(400).json({ error: 'Data tidak lengkap' });

    // Simpan pending payment ke Upstash
    const paymentData = {
      email,
      plan,
      ref,
      status: 'pending',
      submittedAt: Date.now()
    };
    await redis.set(`pb_payment:${ref}`, JSON.stringify(paymentData));
    
    // Tambahkan ke list pending
    await redis.lpush('pb_payments_pending', ref);

    // Notif Telegram ke Aldo
    const TG_TOKEN = '8644597217:AAHUiw9LScsWcI0vhSXGHLnZkVwFq2CWNjc';
    const TG_CHAT = '1921192601';
    const msg = `💰 *Payment Baru - Infinity SenderBlast!*\n\n📧 Email: ${email}\n📦 Paket: ${plan.toUpperCase()}\n🔖 Ref: \`${ref}\`\n\n👉 Approve di: https://infinitysenderblast.vercel.app/admin`;
    
    await fetch(`https://api.telegram.org/bot${TG_TOKEN}/sendMessage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: TG_CHAT, text: msg, parse_mode: 'Markdown' })
    }).catch(() => {});

    return res.status(200).json({ success: true });
  } catch(e) {
    return res.status(500).json({ error: 'Server error: ' + e.message });
  }
};
