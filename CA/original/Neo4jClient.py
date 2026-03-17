from absl.testing.parameterized import parameters
from dns.e164 import query
from neo4j import GraphDatabase
from redis.commands.search.aggregation import Limit


class Neo4jClient:
    def __init__(self, uri, user, password):
        self.__uri = uri
        self.__user = user
        self.__password = password
        self.__driver = GraphDatabase.driver(self.__uri, auth=(self.__user, self.__password))

    def close(self):
        """Close the Neo4j driver."""
        if self.__driver:
            self.__driver.close()

    def run_query(self, query, parameters=None):
        """Run a Cypher query and return the results."""
        try:
            with self.__driver.session() as session:
                result = session.run(query, parameters)
                return [record.data() for record in result]
        except Exception as e:
            print(f"Query failed: {e}")
            raise

    def paintings_info(self):
        """Get information about paintings and their associated AOIs."""
        query = """
        MATCH (a:Object:Painting)-[:has_AOI]-(b:AOI)
        RETURN a, b
        """
        return self.run_query(query)

    def conversation_history_____(self, actor_id, agent_id):
        """Get conversation history for a given actor."""
        query = f"""
        MATCH (a:Actor)-[:performs]->(b:Action:VerbalCommunication)-[:interacting_actor]->(c:Actor)
        MATCH (c:Actor)-[:performs]->(f:Action:VerbalCommunication)-[:interacting_actor]->(a:Actor)
        MATCH (f)-[:has_text]-(t2:Text)
        MATCH (b)-[:has_text]-(t:Text)
        WHERE ID(a) = {actor_id} AND ID(c) = {agent_id}
        RETURN t.text AS userTexts, t2.text AS yourResponses
        """
        return []

    def conversation_history(self, actor_id, agent_id):
        """Get conversation history for a given actor."""
        query = f"""
        MATCH (a:Actor:User)--(b:Action:VerbalCommunication)--(c:Actor:Agent)
        MATCH (b)--(j:Text)
        MATCH (b)--(t:Time:StartTime)
        WHERE ID(a) = {actor_id} AND ID(c) = {agent_id}
        WITH 
            t.startTime AS tim,
            j.text AS userText,
            CASE 
                WHEN (a)-[:performs]->(b) THEN 'User'  
                WHEN (c)-[:performs]->(b) THEN 'Agent' 
                ELSE 'Unknown'  // In case there's a problem with the relationships
            END AS speaker
        RETURN tim as Time, speaker as Speaker, userText as Text 
        ORDER BY tim Desc
        limit 20
        """

        return self.run_query(query)

    def conversation_history_object(self, actor_id, agent_id, objectName):
        """Get conversation history for a given actor."""
        query = f"""
        MATCH (a:Actor:User)--(b:Action:VerbalCommunication)--(c:Actor:Agent)
        MATCH (b)--(j:Text)
        MATCH (b)--(t:Time:StartTime)
        MATCH (a)--(b2:Action:Observing)--(k:Object:Painting {{objectName:{objectName}}})
        WHERE ID(a) = {actor_id} AND ID(c) = {agent_id}
        WITH 
            t.startTime AS tim,
            j.text AS userText,
            CASE 
                WHEN (a)-[:performs]->(b) THEN 'User'  
                WHEN (c)-[:performs]->(b) THEN 'Agent' 
                ELSE 'Unknown'  // In case there's a problem with the relationships
            END AS speaker
        RETURN Distinct tim as Time, speaker as Speaker, userText as Text 
        ORDER BY tim Desc
        """

        return self.run_query(query)

    def get_info_about_aoi(self, node_name):
        """Get information about a specific AOI by name."""
        query = f"""
        MATCH (a:AOI {{name: '{node_name}'}})
        RETURN a
        """

        return self.run_query(query)

    def get_info_about_object(self, node_name):
        """Get information about a specific Object and its AOIs."""
        query = f"""
        MATCH (a:Object {{objectName: '{node_name}'}})-[:has_AOI]->(b:AOI)
        RETURN a, b
        """
        return self.run_query(query)

    def get_last_obj(self, actor_id):
        """Get the most recent painting interacted with by an actor."""
        query = f"""
        MATCH (c:Actor)-[:performs]->(a:Action:Observing)-[:interacting_object]->(b:Object:Painting)
        MATCH (a)-[:has_time]->(t:Time:StartTime)
        MATCH (a)-[:has_time]->(t2:Time:Duration)
        MATCH (b)-[:has_AOI]->(d:AOI)
        WHERE ID(c) = {actor_id} and t2.duration > 0.1
        WITH b, t, t2
        ORDER BY t.startTime DESC
        LIMIT 1  
        MATCH (b)-[:has_AOI]->(d:AOI)  
        RETURN b.name AS name_of_object, b AS object_information, collect(d) AS areas_in_painting_information
        """
        return self.run_query(query)

    def get_last_obj_id(self, actor_id):
        print("getting last obj id")
        """Get the most recent painting interacted with by an actor."""
        query = f"""
        MATCH (c:Actor)-[:performs]->(a:Action:Observing)-[:interacting_object]->(b:Object:Painting)
        MATCH (a)-[:has_time]->(t:Time:StartTime)
        MATCH (a)-[:has_time]->(t2:Time:Duration)
        MATCH (b)-[:has_AOI]->(d:AOI)
        WHERE ID(c) = {actor_id} and t2.duration > 0.1
        WITH b, t, t2
        ORDER BY t.startTime DESC
        RETURN b.objectName
        LIMIT 1
        """
        return self.run_query(query)

    def get_last_time_of_interaction(self, actor_id, agent_id):
        """Get the most recent painting interacted with by an actor."""
        query = f"""
        MATCH (a:Actor:User)--(b:Action:VerbalCommunication)--(c:Actor:Agent)
        MATCH (b)--(t:Time:StartTime)
        WHERE ID(a) = {actor_id} and ID(c) = {agent_id}
        Return t.startTime as tim
        ORDER BY t.startTime DESC
        limit 1
        """
        return self.run_query(query)

    def get_last_aoi(self, actor_id):
        """Get the most recent AOI interacted with by an actor."""
        query = f"""
        MATCH (c:Actor)-[:performs]->(a:Action:Observing)-[:interacting_AOI]->(b:AOI)
        MATCH (a)-[:has_time]->(t:Time:StartTime)
        MATCH (a)-[:has_time]->(t2:Time:Duration)
        WHERE ID(c) = {actor_id} and t2.duration > 0.1
        WITH b, t, t2
        ORDER BY t.startTime DESC
        RETURN b.name, b.description
        LIMIT 1
        """
        return self.run_query(query)

    def get_last_aoi_id(self, actor_id):
        """Get the most recent AOI interacted with by an actor."""
        query = f"""
        MATCH (c:Actor)-[:performs]->(a:Action:Observing)-[:interacting_AOI]->(b:AOI)
        MATCH (a)-[:has_time]->(t:Time:StartTime)
        MATCH (a)-[:has_time]->(t2:Time:Duration)
        WHERE ID(c) = {actor_id} and t2.duration > 0.1
        WITH b, t, t2
        ORDER BY t.startTime DESC
        RETURN b.name
        LIMIT 1
        """
        return self.run_query(query)

    def get_wrong_aoi(self, actor_id):
        name = self.get_last_aoi(actor_id)[0]['b.name']
        query = f"""
                MATCH (c:Actor)-[:performs]->(a:Action)-[:interacting_AOI]->(b:AOI)
                WHERE ID(c) = {actor_id} AND b.name <> '{name}'
                WITH b
                ORDER BY rand()
                RETURN b.name, b.description
                LIMIT 1
                """
        return self.run_query(query)

    def import_conv(self, firstActor_id, secondActor_id, text, start_time):
        # Construct the query with dynamic labels handled as part of the query string
        query = f"""
            MATCH (c:Actor) 
            WHERE ID(c) = {firstActor_id}
            MATCH (b:Actor)
            WHERE ID(b) = {secondActor_id}
            CREATE (c)-[:performs]->(a:Action:VerbalCommunication)
            CREATE (a)-[:interacting_actor]->(b)
            CREATE (a)-[:has_text]->(r:Text {{text: '{text}'}})
            CREATE (a)-[:has_time]->(t:Time:StartTime {{startTime: {start_time}}})
        """

        #print(query)
        # Run the query
        parameters = {'text' : text}
        return self.run_query(query, parameters)

    def creating_an_agent(self, actorID, time):
        query = f"""    
                MATCH (q:Actor:User) 
                WHERE ID(q) = {actorID}
                MATCH (q)--(e:Event)
                WITH e
                CREATE (a:Actor:Agent {{created_at:{time}}})  
                WITH a, e
                MATCH (b:Environment {{name: "HERE: Black in Rembrandt’s Time"}})
                MERGE (a)-[:in_environment]->(b)
                MERGE (a)-[:participates_in]->(e)
                RETURN ID(a) AS agentID
                LIMIT 1
                """
        return self.run_query(query)

    def get_agent_id(self):
        query = f"""    
                    MATCH (n:Actor:Agent)
                    return ID(n) as id
                    order by n.created_at desc
                    limit 1
                """
        return self.run_query(query)

    def get_user_id(self):
        query = f"""    
                    MATCH (n:Actor:User)
                    return ID(n) as id
                    order by n.created_at desc
                    limit 1
                """
        return self.run_query(query)

    def get_last_agent_response(self,actorID,agentID):
        query = f"""
                MATCH (a:Actor:Agent)-[:performs]->(b:Action:VerbalCommunication)-[:interacting_actor]->(c:Actor:User)
                MATCH (b)-[:has_text]-(t:Text)
                MATCH (b)-[:has_time]-(f:Time:StartTime)
                WHERE ID(a) = {agentID} and ID(c) = {actorID}
                WITH t.text AS responseText, f.startTime AS startTime
                ORDER BY startTime DESC
                RETURN responseText AS YourLastResponseToUser
                LIMIT 1
                """

        return self.run_query(query)


    def get_image_of_painting(self,actor_id):
        query = f"""
                MATCH (c:Actor)-[:performs]->(a:Action:Observing)-[:interacting_object]->(b:Object:Painting)
                MATCH (a)-[:has_time]->(t:Time:StartTime)
                WHERE ID(c) = {actor_id}
                WITH b, t
                ORDER BY t.startTime DESC
                RETURN b.img as img_path
                LIMIT 1
                """

        return self.run_query(query)


    def get_time_spend_on_aois(self, objName,actorID):
        query = f"""
        MATCH(a:TimeSpend)--(b:Measure)--(c:Actor:User) 
        MATCH (a)--(d:AOI)--(o:Object:Painting {{objectName : '{objName}'}})
        WHERE ID(c) = {actorID}
        RETURN a.timeSpendOnObject as timeSpendOnAOIs, d.name as AOI_name
        """
        return self.run_query(query)

    def get_number_of_fixation_count(self, objName,actorID):
        query = f"""
        MATCH(a:FixationCount)--(b:Measure)--(c:Actor:User) 
        MATCH (a)--(d:AOI)--(o:Object:Painting {{objectName : '{objName}'}})
        WHERE ID(c) = {actorID}
        RETURN a.fixationCount as fixationCount, d.name as AOI_name
        """
        return self.run_query(query)

    def get_number_of_transition_between_AOIs(self, objName, actorID):
        query = f"""
                MATCH(a:TransitionsBetweenAOIs)--(b:Measure)--(c:Actor:User) 
                MATCH (a)--(o:Object:Painting {{objectName : '{objName}'}})
                WHERE ID(c) = {actorID}
                RETURN a.numberOfTransitions as transitionCount
                LIMIT 1
                """
        return self.run_query(query)

    def get_graph_data(self):
        query = f"""
                MATCH (c:Object)-[:has_AOI]-(a:AOI)
                return c,a
                """

        return self.run_query(query)

