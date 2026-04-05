const { Redis } = require('@upstash/redis');

const redis = new Redis({
  url: process.env.UPSTASH_REDIS_REST_URL,
  token: process.env.UPSTASH_REDIS_REST_TOKEN,
});

const ADMIN_PASS = process.env.ADMIN_PASSWORD || 'infinity2026admin';
const PLAN_CONFIG = {
  starter: { dailyLimit: 500, maxNumbers: 2, label: 'Starter' },
  pro: { dailyLimit: 99999, maxNumbers: 5, label: 'Pro' }
};

module.exports = async (req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
  if (req.method === 'OPTIONS') return res.status(200).end();

  const adminPass = req.headers.authorization?.replace('Bearer ', '');
  if (adminPass !== ADMIN_PASS) return res.status(401).json({ error: 'Unauthorized' });

  try {
    if (req.method === 'GET') {
      // List semua pending payments
      const refs = await redis.lrange('pb_payments_pending', 0, 50);
      const payments = [];
      for (const ref of refs) {
        const raw = await redis.get(`pb_payment:${ref}`);
        if (raw) {
          const data = typeof raw === 'string' ? JSON.parse(raw) : raw;
          payments.push(data);
        }
      }
      return res.status(200).json({ success: true, payments });
    }

    if (req.method === 'POST') {
      const { ref, action } = req.body; // action: 'approve' | 'reject'
      if (!ref || !action) return res.status(400).json({ error: 'ref dan action wajib' });

      const raw = await redis.get(`pb_payment:${ref}`);
      if (!raw) return res.status(404).json({ error: 'Payment tidak ditemukan' });
      
      const payment = typeof raw === 'string' ? JSON.parse(raw) : raw;

      if (action === 'approve') {
        // Upgrade user plan
        const userRaw = await redis.get(`pb_user:${payment.email}`);
        if (!userRaw) return res.status(404).json({ error: 'User tidak ditemukan' });
        
        const user = typeof userRaw === 'string' ? JSON.parse(userRaw) : userRaw;
        const planConfig = PLAN_CONFIG[payment.plan] || PLAN_CONFIG.starter;
        
        user.plan = payment.plan;
        user.dailyLimit = planConfig.dailyLimit;
        user.maxNumbers = planConfig.maxNumbers;
        user.upgradedAt = Date.now();

        await redis.set(`pb_user:${payment.email}`, JSON.stringify(user));
        payment.status = 'approved';
        payment.approvedAt = Date.now();
      } else {
        payment.status = 'rejected';
      }

      await redis.set(`pb_payment:${ref}`, JSON.stringify(payment));
      await redis.lrem('pb_payments_pending', 1, ref);

      return res.status(200).json({ success: true, message: `Payment ${action}d` });
    }
  } catch(e) {
    return res.status(500).json({ error: 'Server error: ' + e.message });
  }
};
