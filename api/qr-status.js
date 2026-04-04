const jwt = require('jsonwebtoken');

const VPS_URL = process.env.VPS_BLAST_URL || 'http://103.145.151.210:8766';
const VPS_SECRET = process.env.VPS_BLAST_SECRET || 'prisilblast_vps_secret_2026';
const JWT_SECRET = process.env.JWT_SECRET || 'prisilblast_secret_2026';

module.exports = async (req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  if (req.method !== 'GET') return res.status(405).end();

  const authHeader = req.headers.authorization;
  if (!authHeader) return res.status(401).json({ error: 'Unauthorized' });
  try { jwt.verify(authHeader.replace('Bearer ', ''), JWT_SECRET); } 
  catch(e) { return res.status(401).json({ error: 'Token tidak valid' }); }

  const { sessionId } = req.query;
  if (!sessionId) return res.status(400).json({ error: 'sessionId wajib' });

  try {
    const response = await fetch(`${VPS_URL}/qr-status?sessionId=${sessionId}`, {
      headers: { 'X-Secret': VPS_SECRET }
    });
    const data = await response.json();
    return res.status(200).json(data);
  } catch(e) {
    return res.status(500).json({ error: 'VPS error: ' + e.message });
  }
};
