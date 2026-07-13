// Deterministic Project 9 fixture: exactly 80 nodes and 150 relationships.
// Designed patterns: shell/UBO chain, PEP/high-risk jurisdiction, sanctions hit,
// four-year court history, and an adverse-media co-mention cluster.

WITH [
  ['Person A','CEO',true,88],['Alice Morgan','CEO',false,32],
  ['Elena Varga','Director',true,91],['Darius Cole','CFO',false,67],
  ['Maya Chen','Director',false,54],['Amir Haddad','Analyst',false,29],
  ['Sofia Petrov','Director',true,79],['Nia Okafor','Counsel',false,35],
  ['Luca Moretti','Director',false,41],['Ana Silva','COO',false,38],
  ['Noah Williams','Director',false,25],['Priya Shah','Director',false,44],
  ['Omar Rahman','Director',false,61],['Eva Novak','Director',false,36],
  ['Sam Reed','Director',false,28],['Iris Wong','Director',false,31]
] AS rows
UNWIND range(0,15) AS i
WITH i, rows[i] AS row
MERGE (p:Person {name:row[0]})
SET p.seed_id=i, p.role=row[1], p.is_pep=row[2], p.risk_score=row[3];

WITH [
  'Company X','Clean Nominee LLC','Clean Holdings LLC','Northstar Imports',
  'Atlas Trading','Orion Logistics','Cedar Ventures','Blue Harbor Ltd',
  'Summit Consulting','Redwood Partners','Silverline GmbH','Eastgate SA',
  'Westbridge PLC','Meridian Foods','Keystone Labs','Pioneer Energy',
  'Portfolio Company 16','Portfolio Company 17','Portfolio Company 18',
  'Portfolio Company 19'
] AS names
UNWIND range(0,19) AS i
WITH i, names[i] AS name
MERGE (c:Company {name:name})
SET c.seed_id=i,
    c.entity_type=CASE WHEN i IN [1,2] THEN 'LLC' ELSE 'Operating company' END,
    c.status='active';

UNWIND range(0,11) AS i
MERGE (a:Address {address_id:'ADDR-' + toString(100+i)})
SET a.seed_id=i, a.street=toString(10+i) + ' Market Street',
    a.city=CASE WHEN i%3=0 THEN 'Port Azure' WHEN i%3=1 THEN 'North City' ELSE 'Lakeview' END;

WITH [
  ['SE-001','OFAC SDN','active'],['SE-002','EU Consolidated','active'],
  ['SE-003','UN Security Council','active'],['SE-004','UK HMT','inactive'],
  ['SE-005','OFAC Sectoral','active']
] AS rows
UNWIND range(0,4) AS i
WITH i, rows[i] AS row
MERGE (s:SanctionsEntry {entry_id:row[0]})
SET s.seed_id=i, s.program=row[1], s.status=row[2];

UNWIND range(0,7) AS i
MERGE (cc:CourtCase {case_id:'CASE-' + toString(2020+i)})
SET cc.seed_id=i, cc.filed_year=2020+i,
    cc.status=CASE WHEN i<6 THEN 'closed' ELSE 'open' END,
    cc.court='Commercial Court';

UNWIND range(0,9) AS i
MERGE (n:NewsArticle {article_id:'NEWS-' + toString(100+i)})
SET n.seed_id=i,
    n.headline=CASE i
      WHEN 0 THEN 'Offshore procurement network under investigation'
      WHEN 1 THEN 'Sanctions screening identifies corporate match'
      ELSE 'KYC monitoring report ' + toString(i) END,
    n.published=date({year:2024,month:1+(i%10),day:1}),
    n.severity=CASE WHEN i<2 THEN 5 ELSE 1+(i%4) END;

WITH [
  ['Khorasan','high'],['Freedonia','low'],['Selvaria','high'],
  ['Montara','medium'],['Rovina','high'],['Pacifica','low'],
  ['Arkania','high'],['Estovia','medium'],['Norland','low']
] AS rows
UNWIND range(0,8) AS i
WITH i, rows[i] AS row
MERGE (j:Jurisdiction {name:row[0]})
SET j.seed_id=i, j.risk_level=row[1];

// 24 OWNS edges. Person A -> Clean Nominee -> Clean Holdings -> Company X
// is the clean shell/ultimate-beneficial-owner chain.
MATCH (p:Person),(c:Company) WHERE p.seed_id=c.seed_id
MERGE (p)-[:OWNS {percent:CASE WHEN p.seed_id=0 THEN 80 ELSE 10+(p.seed_id%6)*10 END}]->(c);
MATCH (p:Person {seed_id:0}),(c:Company {seed_id:1})
MERGE (p)-[:OWNS {percent:80}]->(c);
MATCH (a:Company {seed_id:1}),(b:Company {seed_id:2})
MERGE (a)-[:OWNS {percent:100}]->(b);
MATCH (a:Company {seed_id:2}),(b:Company {seed_id:0})
MERGE (a)-[:OWNS {percent:100}]->(b);
UNWIND range(3,7) AS i
MATCH (a:Company {seed_id:i}),(b:Company {seed_id:i+1})
MERGE (a)-[:OWNS {percent:30+i}]->(b);

// 20 directors; Person A is both Company X's CEO and a PEP.
MATCH (c:Company),(p:Person) WHERE p.seed_id=c.seed_id%16
MERGE (p)-[:DIRECTOR_OF]->(c);

// 16 residences and 20 company registrations.
MATCH (p:Person),(a:Address) WHERE a.seed_id=p.seed_id%12
MERGE (p)-[:RESIDES_AT]->(a);
MATCH (c:Company),(a:Address) WHERE a.seed_id=c.seed_id%12
MERGE (c)-[:REGISTERED_AT]->(a);

// 19 case links, including four Company X cases across 2020-2023.
MATCH (c:Company),(cc:CourtCase)
WHERE c.seed_id<16 AND cc.seed_id=c.seed_id%8
MERGE (c)-[:INVOLVED_IN]->(cc);
UNWIND range(1,3) AS i
MATCH (c:Company {seed_id:0}),(cc:CourtCase {seed_id:i})
MERGE (c)-[:INVOLVED_IN]->(cc);

// 25 news links. NEWS-100 is the designed adverse-media cluster.
MATCH (c:Company),(n:NewsArticle) WHERE n.seed_id=c.seed_id%10
MERGE (c)-[:MENTIONED_IN]->(n);
UNWIND range(0,4) AS i
MATCH (p:Person {seed_id:i}),(n:NewsArticle {seed_id:0})
MERGE (p)-[:MENTIONED_IN]->(n);

// Eight sanctions matches, including a direct active hit on Company X.
MATCH (c:Company),(s:SanctionsEntry)
WHERE c.seed_id<8 AND s.seed_id=c.seed_id%5
MERGE (c)-[:MATCHED_TO {confidence:0.91+c.seed_id*0.01}]->(s);

// 18 jurisdiction links: all addresses plus six directly subject companies.
// Company X's registered address is subject to high-risk Khorasan.
MATCH (a:Address),(j:Jurisdiction) WHERE j.seed_id=a.seed_id%9
MERGE (a)-[:SUBJECT_TO]->(j);
MATCH (c:Company),(j:Jurisdiction)
WHERE c.seed_id<6 AND j.seed_id=c.seed_id%9
MERGE (c)-[:SUBJECT_TO]->(j);
