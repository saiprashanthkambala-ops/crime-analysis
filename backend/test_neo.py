import truststore
truststore.inject_into_ssl()

from neo4j import GraphDatabase

if __name__ == "__main__":
    print("hii")
    try:
        driver = GraphDatabase.driver(
            "neo4j+s://00dd013d.databases.neo4j.io",
            auth=("00dd013d", "0IKMsxytF-fXg1Ud0US_Aj3IFn-tIfGE1vBEo-p2jPY"),
        )
        with driver.session() as session:
            print(session.run("RETURN 1 AS ok").single())
        driver.close()
    except Exception as e:
        print("Neo4j test error:", e)