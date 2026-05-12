import 'dotenv/config';
import { Pool } from 'pg';

const pool = new Pool({ connectionString: process.env.NEON_DB_URL });

async function migrate() {
  const client = await pool.connect();
  try {
    console.log('🚀 Starting migration...\n');

    // ── Drop all tables CASCADE ────────────────────────────────────────────────
    console.log('🗑️  Dropping existing tables...');
    await client.query(`
      DROP TABLE IF EXISTS
        competitor_ad_data,
        search_term_data,
        trend_data,
        brain_dependencies,
        share_links,
        quarterly_industry_reports,
        disruption_reports,
        opportunities,
        marketing_copy_library,
        offer_intelligence,
        success_stories,
        avatar_generation_jobs,
        marketing_copy_library,
        customer_avatars,
        insights,
        raw_source_data,
        research_jobs,
        niches
      CASCADE;
    `);
    console.log('   ✅ All tables dropped\n');

    // ── FOUNDATION ────────────────────────────────────────────────────────────
    console.log('🏗️  Creating foundation tables...');

    await client.query(`
      CREATE TABLE niches (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        slug VARCHAR(100) NOT NULL UNIQUE,
        description TEXT,
        status VARCHAR(50) NOT NULL DEFAULT 'active',
        data_sources JSON,
        research_frequency JSON,
        metadata JSON,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
      );
    `);
    console.log('   ✅ niches');

    await client.query(`
      CREATE TABLE research_jobs (
        id SERIAL PRIMARY KEY,
        niche_id INTEGER NOT NULL REFERENCES niches(id),
        job_type VARCHAR(100) NOT NULL,
        status VARCHAR(50) NOT NULL DEFAULT 'pending',
        brain_name VARCHAR(100),
        priority INTEGER NOT NULL DEFAULT 5,
        payload JSON,
        result JSON,
        error_message TEXT,
        started_at TIMESTAMP,
        completed_at TIMESTAMP,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
      );
    `);
    console.log('   ✅ research_jobs');

    await client.query(`
      CREATE TABLE raw_source_data (
        id SERIAL PRIMARY KEY,
        niche_id INTEGER NOT NULL REFERENCES niches(id),
        source_type VARCHAR(50) NOT NULL,
        source_url TEXT,
        source_id VARCHAR(255),
        title TEXT,
        content TEXT,
        author VARCHAR(255),
        score INTEGER,
        engagement_metrics JSON,
        raw_data JSON,
        collected_at TIMESTAMP NOT NULL DEFAULT NOW(),
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
      );
    `);
    console.log('   ✅ raw_source_data\n');

    // ── INTELLIGENCE ──────────────────────────────────────────────────────────
    console.log('🧠 Creating intelligence tables...');

    await client.query(`
      CREATE TABLE insights (
        id SERIAL PRIMARY KEY,
        niche_id INTEGER NOT NULL REFERENCES niches(id),
        insight_type VARCHAR(100) NOT NULL,
        title TEXT NOT NULL,
        summary TEXT,
        body TEXT,
        confidence_score DECIMAL(3,2),
        source_ids JSON,
        tags JSON,
        is_actionable BOOLEAN NOT NULL DEFAULT false,
        expires_at TIMESTAMP,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
      );
    `);
    console.log('   ✅ insights');

    await client.query(`
      CREATE TABLE customer_avatars (
        id SERIAL PRIMARY KEY,
        niche_id INTEGER NOT NULL REFERENCES niches(id),
        name TEXT NOT NULL,
        avatar_type VARCHAR(100),
        age_range VARCHAR(50),
        income_range VARCHAR(100),
        psychographics JSON,
        pain_points JSON,
        desires JSON,
        objections JSON,
        empathy_map JSON,
        buying_triggers JSON,
        preferred_channels JSON,
        is_primary BOOLEAN NOT NULL DEFAULT false,
        version INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
      );
    `);
    console.log('   ✅ customer_avatars');

    await client.query(`
      CREATE TABLE avatar_generation_jobs (
        id SERIAL PRIMARY KEY,
        niche_id INTEGER NOT NULL REFERENCES niches(id),
        avatar_id INTEGER REFERENCES customer_avatars(id),
        status VARCHAR(50) NOT NULL DEFAULT 'pending',
        generation_config JSON,
        source_data_ids JSON,
        ai_model VARCHAR(100),
        tokens_used INTEGER,
        result_summary JSON,
        error_message TEXT,
        started_at TIMESTAMP,
        completed_at TIMESTAMP,
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
      );
    `);
    console.log('   ✅ avatar_generation_jobs');

    await client.query(`
      CREATE TABLE success_stories (
        id SERIAL PRIMARY KEY,
        niche_id INTEGER NOT NULL REFERENCES niches(id),
        title TEXT NOT NULL,
        source_type VARCHAR(50),
        source_url TEXT,
        protagonist_profile JSON,
        before_state TEXT,
        after_state TEXT,
        transformation TEXT,
        key_mechanism TEXT,
        quantified_results JSON,
        emotional_arc JSON,
        usable_hooks JSON,
        verified BOOLEAN NOT NULL DEFAULT false,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
      );
    `);
    console.log('   ✅ success_stories');

    await client.query(`
      CREATE TABLE offer_intelligence (
        id SERIAL PRIMARY KEY,
        niche_id INTEGER NOT NULL REFERENCES niches(id),
        offer_name TEXT NOT NULL,
        competitor_name TEXT,
        offer_type VARCHAR(100),
        price_point DECIMAL(10,2),
        pricing_model VARCHAR(100),
        core_promise TEXT,
        unique_mechanism TEXT,
        bonuses JSON,
        guarantees JSON,
        testimonials_summary JSON,
        conversion_elements JSON,
        weaknesses JSON,
        strengths JSON,
        source_url TEXT,
        last_seen_at TIMESTAMP,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
      );
    `);
    console.log('   ✅ offer_intelligence');

    await client.query(`
      CREATE TABLE marketing_copy_library (
        id SERIAL PRIMARY KEY,
        niche_id INTEGER NOT NULL REFERENCES niches(id),
        copy_type VARCHAR(100) NOT NULL,
        copy_angle VARCHAR(100),
        content TEXT NOT NULL,
        target_avatar_id INTEGER REFERENCES customer_avatars(id),
        performance_data JSON,
        ai_generated BOOLEAN NOT NULL DEFAULT true,
        approved BOOLEAN NOT NULL DEFAULT false,
        tags JSON,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
      );
    `);
    console.log('   ✅ marketing_copy_library');

    await client.query(`
      CREATE TABLE opportunities (
        id SERIAL PRIMARY KEY,
        niche_id INTEGER NOT NULL REFERENCES niches(id),
        title TEXT NOT NULL,
        opportunity_type VARCHAR(100),
        description TEXT,
        market_gap TEXT,
        target_segment TEXT,
        estimated_market_size JSON,
        effort_level VARCHAR(50),
        potential_revenue JSON,
        time_to_market VARCHAR(100),
        risk_factors JSON,
        validation_ideas JSON,
        status VARCHAR(50) NOT NULL DEFAULT 'identified',
        priority_score DECIMAL(3,2),
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
      );
    `);
    console.log('   ✅ opportunities');

    await client.query(`
      CREATE TABLE disruption_reports (
        id SERIAL PRIMARY KEY,
        niche_id INTEGER NOT NULL REFERENCES niches(id),
        report_title TEXT NOT NULL,
        report_period VARCHAR(100),
        disruption_signals JSON,
        emerging_technologies JSON,
        regulatory_changes JSON,
        consumer_behavior_shifts JSON,
        competitive_moves JSON,
        threat_level VARCHAR(50),
        opportunity_level VARCHAR(50),
        recommended_actions JSON,
        executive_summary TEXT,
        published_at TIMESTAMP,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
      );
    `);
    console.log('   ✅ disruption_reports');

    await client.query(`
      CREATE TABLE quarterly_industry_reports (
        id SERIAL PRIMARY KEY,
        niche_id INTEGER NOT NULL REFERENCES niches(id),
        quarter VARCHAR(10) NOT NULL,
        report_title TEXT NOT NULL,
        market_overview TEXT,
        key_trends JSON,
        top_performers JSON,
        consumer_sentiment JSON,
        pricing_trends JSON,
        channel_performance JSON,
        ai_generated_insights JSON,
        data_sources_used JSON,
        confidence_metrics JSON,
        published_at TIMESTAMP,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
      );
    `);
    console.log('   ✅ quarterly_industry_reports\n');

    // ── SUPPORTING ────────────────────────────────────────────────────────────
    console.log('🔗 Creating supporting tables...');

    await client.query(`
      CREATE TABLE share_links (
        id SERIAL PRIMARY KEY,
        niche_id INTEGER NOT NULL REFERENCES niches(id),
        token VARCHAR(255) NOT NULL UNIQUE,
        link_type VARCHAR(100) NOT NULL,
        resource_id INTEGER,
        resource_table VARCHAR(100),
        permissions JSON,
        view_count INTEGER NOT NULL DEFAULT 0,
        expires_at TIMESTAMP,
        created_by VARCHAR(255),
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
      );
    `);
    console.log('   ✅ share_links');

    await client.query(`
      CREATE TABLE brain_dependencies (
        id SERIAL PRIMARY KEY,
        niche_id INTEGER NOT NULL REFERENCES niches(id),
        brain_name VARCHAR(100) NOT NULL,
        brain_type VARCHAR(100) NOT NULL,
        display_name TEXT,
        description TEXT,
        depends_on JSON,
        config JSON,
        schedule VARCHAR(100),
        last_run_at TIMESTAMP,
        next_run_at TIMESTAMP,
        run_count INTEGER NOT NULL DEFAULT 0,
        is_enabled BOOLEAN NOT NULL DEFAULT true,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
      );
    `);
    console.log('   ✅ brain_dependencies\n');

    // ── EXTENSIBLE ────────────────────────────────────────────────────────────
    console.log('📈 Creating extensible tables...');

    await client.query(`
      CREATE TABLE trend_data (
        id SERIAL PRIMARY KEY,
        niche_id INTEGER NOT NULL REFERENCES niches(id),
        term TEXT NOT NULL,
        source VARCHAR(50) NOT NULL,
        trend_value DECIMAL(10,4),
        trend_direction VARCHAR(20),
        geo VARCHAR(10),
        time_range VARCHAR(50),
        related_queries JSON,
        breakdown JSON,
        recorded_at TIMESTAMP NOT NULL DEFAULT NOW(),
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
      );
    `);
    console.log('   ✅ trend_data');

    await client.query(`
      CREATE TABLE search_term_data (
        id SERIAL PRIMARY KEY,
        niche_id INTEGER NOT NULL REFERENCES niches(id),
        keyword TEXT NOT NULL,
        search_volume INTEGER,
        cpc DECIMAL(8,4),
        competition VARCHAR(20),
        competition_score DECIMAL(5,4),
        intent VARCHAR(50),
        serp_features JSON,
        related_keywords JSON,
        source VARCHAR(50),
        recorded_at TIMESTAMP NOT NULL DEFAULT NOW(),
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
      );
    `);
    console.log('   ✅ search_term_data');

    await client.query(`
      CREATE TABLE competitor_ad_data (
        id SERIAL PRIMARY KEY,
        niche_id INTEGER NOT NULL REFERENCES niches(id),
        competitor_name TEXT NOT NULL,
        platform VARCHAR(50) NOT NULL,
        ad_id VARCHAR(255),
        ad_type VARCHAR(50),
        headline TEXT,
        body_text TEXT,
        cta VARCHAR(100),
        media_url TEXT,
        landing_page_url TEXT,
        estimated_spend JSON,
        estimated_impressions JSON,
        running_since TIMESTAMP,
        last_seen_at TIMESTAMP,
        ad_metadata JSON,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
      );
    `);
    console.log('   ✅ competitor_ad_data\n');

    console.log('✨ Migration complete! 17 tables created successfully.');
  } catch (err) {
    console.error('❌ Migration failed:', err);
    process.exit(1);
  } finally {
    client.release();
    await pool.end();
  }
}

migrate();
