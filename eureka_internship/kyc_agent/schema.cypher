// Literal Project 9 schema for Neo4j 5.
CREATE CONSTRAINT person_name IF NOT EXISTS FOR (n:Person) REQUIRE n.name IS UNIQUE;
CREATE CONSTRAINT company_name IF NOT EXISTS FOR (n:Company) REQUIRE n.name IS UNIQUE;
CREATE CONSTRAINT address_id IF NOT EXISTS FOR (n:Address) REQUIRE n.address_id IS UNIQUE;
CREATE CONSTRAINT sanctions_entry_id IF NOT EXISTS FOR (n:SanctionsEntry) REQUIRE n.entry_id IS UNIQUE;
CREATE CONSTRAINT court_case_id IF NOT EXISTS FOR (n:CourtCase) REQUIRE n.case_id IS UNIQUE;
CREATE CONSTRAINT news_article_id IF NOT EXISTS FOR (n:NewsArticle) REQUIRE n.article_id IS UNIQUE;
CREATE CONSTRAINT jurisdiction_name IF NOT EXISTS FOR (n:Jurisdiction) REQUIRE n.name IS UNIQUE;

CREATE INDEX person_pep IF NOT EXISTS FOR (n:Person) ON (n.is_pep);
CREATE INDEX company_status IF NOT EXISTS FOR (n:Company) ON (n.status);
CREATE INDEX jurisdiction_risk IF NOT EXISTS FOR (n:Jurisdiction) ON (n.risk_level);
CREATE INDEX court_case_year IF NOT EXISTS FOR (n:CourtCase) ON (n.filed_year);
CREATE FULLTEXT INDEX entity_names IF NOT EXISTS
FOR (n:Person|Company) ON EACH [n.name];
