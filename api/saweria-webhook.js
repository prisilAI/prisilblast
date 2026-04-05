const { Redis } = require('@upstash/redis');
const crypto = require('crypto');

const redis = new Redis({
  url: process.env.UPSTASH_REDIS_REST_URL,
  token: process.env.UPSTASH_REDIS_REST_TOKEN,
});

// Mapping nominal → plan
const AMOUNT_PLAN = {
  49000: { plan: 'starter', label: 'Starter', dailyLimit: 500, maxNumbers: 2 },
  149000: { plan: 'pro', label: 'Pro', dailyLimit: 99999, maxNumbers: 5 },
  9000: { plan: 'starter', label: 'Starter (Test)', dailyLimit: 500, maxNumbers: 2 }, // test
};

module.exports = async (req, res) => {
  if (req.method !== 'POST') return res.status(405).end();

  try {
    const { amount_raw, donatur_name, donatur_email, message } = req.body;
    const amount = parseInt(amount_raw || req.body.amount || 0);

    console.log('[Saweria Webhook]', { amount, donatur_name, donatur_email, message });

    // Cari plan berdasarkan amount
    let planData = null;
    for (const [nominal, data] of Object.entries(AMOUNT_PLAN)) {
      if (amount >= parseInt(nominal)) {
        planData = data;
        break;
      }
    }

    if (!planData) {
      console.log('[Saweria] Amount tidak match:', amount);
      return res.status(200).json({ ok: true, note: 'amount tidak match plan' });
    }

    // Cari email dari message atau donatur_email
    const emailMatch = (message || '').match(/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/);
    const userEmail = emailMatch ? emailMatch[0] : donatur_email;

    if (!userEmail) {
      // Simpan payment untuk verifikasi manual
      await redis.set(`pb_payment:saweria:${Date.now()}`, JSON.stringify({
        amount, donatur_name, donatur_email, message,
        plan: planData.plan, status: 'pending_email',
        createdAt: Date.now()
      }));
      return res.status(200).json({ ok: true, note: 'email tidak ditemukan, perlu verifikasi manual' });
    }

    // Upgrade user
    const raw = await redis.get(`pb_user:${userEmail}`);
    if (raw) {
      const user = typeof raw === 'string' ? JSON.parse(raw) : raw;
      user.plan = planData.plan;
      user.dailyLimit = planData.dailyLimit;
      user.maxNumbers = planData.maxNumbers;
      user.upgradedAt = Date.now();
      await redis.set(`pb_user:${userEmail}`, JSON.stringify(user));
      console.log(`[Saweria] ✅ User ${userEmail} upgraded to ${planData.plan}`);
    } else {
      // User belum daftar, simpan untuk nanti
      await redis.set(`pb_pending_upgrade:${userEmail}`, JSON.stringify({
        plan: planData.plan, dailyLimit: planData.dailyLimit,
        maxNumbers: planData.maxNumbers, amount, createdAt: Date.now()
      }));
    }

    return res.status(200).json({ ok: true, upgraded: userEmail, plan: planData.plan });
  } catch(e) {
    console.error('[Saweria Error]', e.message);
    return res.status(500).json({ error: e.message });
  }
};
