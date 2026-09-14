import truststore
truststore.inject_into_ssl()

from neo4j import GraphDatabase
print("hii")
driver = GraphDatabase.driver(
    "neo4j+s://00dd013d.databases.neo4j.io",
    auth=("00dd013d", "0IKMsxytF-fXg1Ud0US_Aj3IFn-tIfGE1vBEo-p2jPY"),
)
with driver.session() as session:
    print(session.run("RETURN 1 AS ok").single())
driver.close()