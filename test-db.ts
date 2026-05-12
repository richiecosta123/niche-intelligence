import 'dotenv/config';
import { Pool } from 'pg';

const pool = new Pool({ connectionString: process.env.NEON_DB_URL });

const EXPECTED_TABLES = [
  'niches',
  'research_jobs',
  'raw_source_data',
  'insights',
  'customer_avatars',
  'avatar_generation_jobs',
  'success_stories',
  'offer_intelligence',
  'marketing_copy_library',
  'opportunities',
  'disruption_reports',
  'quarterly_industry_reports',
  'share_links',
  'brain_dependencies',
  'trend_data',
  'search_term_data',
  'competitor_ad_data',
];

async function testDb() {
  const client = await pool.connect();
  try {
    console.log('🔍 Verifying database schema...\n');

    // Check all tables exist
    const { rows } = await client.query(`
      SELECT table_name
      FROM information_schema.tables
      WHERE table_schema = 'public'
        AND table_type = 'BASE TABLE'
      ORDER BY table_name;
    `);

    const existingTables = rows.map((r: { table_name: string }) => r.table_name);
    console.log(`📋 Tables found in database (${existingTables.length}):`);

    let allPresent = true;
    for (const table of EXPECTED_TABLES) {
      const exists = existingTables.includes(table);
      console.log(`   ${exists ? '✅' : '❌'} ${table}`);
      if (!exists) allPresent = false;
    }

    console.log();
    if (!allPresent) {
      console.error('❌ Some expected tables are missing!');
      process.exit(1);
    }

    // Test basic insert/select on niches
    console.log('🧪 Testing basic operations on niches...');
    const testSlug = `test-niche-${Date.now()}`;

    const insert = await client.query(
      `INSERT INTO niches (name, slug, description, data_sources)
       VALUES ($1, $2, $3, $4)
       RETURNING id, name, slug`,
      [
        'Test Niche',
        testSlug,
        'Temporary test record',
        JSON.stringify({ reddit: ['r/test'], youtube: [] }),
      ]
    );
    const inserted = insert.rows[0];
    console.log(`   ✅ INSERT → id=${inserted.id}, name="${inserted.name}", slug="${inserted.slug}"`);

    const select = await client.query('SELECT * FROM niches WHERE id = $1', [inserted.id]);
    console.log(`   ✅ SELECT → found ${select.rows.length} row(s)`);

    // Test FK insert into brain_dependencies
    const bdInsert = await client.query(
      `INSERT INTO brain_dependencies (niche_id, brain_name, brain_type, display_name)
       VALUES ($1, $2, $3, $4)
       RETURNING id`,
      [inserted.id, 'test_brain', 'analyst', 'Test Brain']
    );
    console.log(`   ✅ FK INSERT → brain_dependencies id=${bdInsert.rows[0].id}`);

    // Cleanup test data
    await client.query('DELETE FROM brain_dependencies WHERE niche_id = $1', [inserted.id]);
    await client.query('DELETE FROM niches WHERE id = $1', [inserted.id]);
    console.log(`   ✅ Cleanup complete\n`);

    console.log(`✨ All ${EXPECTED_TABLES.length} tables verified. Database is healthy!`);
  } catch (err) {
    console.error('❌ Test failed:', err);
    process.exit(1);
  } finally {
    client.release();
    await pool.end();
  }
}

testDb();
