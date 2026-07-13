// Production example for Neo4j Enterprise. Run as an administrator and provide
// the $reader_password parameter; never commit the actual password.
CREATE ROLE kyc_reader_role IF NOT EXISTS;
GRANT ACCESS ON DATABASE neo4j TO kyc_reader_role;
GRANT MATCH {*} ON GRAPH neo4j NODES * TO kyc_reader_role;
GRANT MATCH {*} ON GRAPH neo4j RELATIONSHIPS * TO kyc_reader_role;
DENY WRITE ON GRAPH neo4j TO kyc_reader_role;
GRANT EXECUTE PROCEDURE db.labels ON DBMS TO kyc_reader_role;
GRANT EXECUTE PROCEDURE db.relationshipTypes ON DBMS TO kyc_reader_role;
GRANT EXECUTE PROCEDURE db.schema.visualization ON DBMS TO kyc_reader_role;

CREATE USER kyc_reader IF NOT EXISTS
SET PASSWORD $reader_password CHANGE NOT REQUIRED;
GRANT ROLE kyc_reader_role TO kyc_reader;
