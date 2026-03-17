using System;
using System.IO;
using System.Linq;
using System.Net;
using System.Text;
using UnityEngine;
using Stopwatch = System.Diagnostics.Stopwatch;


/// <summary>
/// Handles all Neo4j communication for gaze/action data.
/// </summary>
public class Neo4jConnector
{
    public string Username = "neo4j";
    public string Password = "12345678";
    public string IP = "localhost";
    public int Port = 7474;
    public bool DebugLog = true;
    public int Limit = 0;

    private string AuthHeader
    {
        get { return Convert.ToBase64String(Encoding.ASCII.GetBytes($"{Username}:{Password}")); }
    }

    /// <summary>
    /// Execute a Cypher query via Neo4j HTTP API.
    /// </summary>
    public string Query(string query)
    {
        var stopwatch = Stopwatch.StartNew();
        string queryLabel = GetQueryLabel(query);
        try
        {
            string url = $"http://{IP}:{Port}/db/neo4j/tx/commit";

            // Clean up query text for valid JSON
            string safeQuery = query
                .Replace("\\", "\\\\")
                .Replace("\"", "\\\"")
                .Replace("\r", "\\r")
                .Replace("\n", "\\n");

            // Construct the JSON payload manually (no external JSON lib needed)
            string jsonPayload = "{\"statements\":[{\"statement\":\"" + safeQuery + "\"}]}";

            //Debug.LogError($"[NEO4J][PAYLOAD CLEAN] {jsonPayload}");

            HttpWebRequest request = (HttpWebRequest)WebRequest.Create(url);
            request.Method = "POST";
            request.ContentType = "application/json";

            string credentials = Convert.ToBase64String(System.Text.Encoding.ASCII.GetBytes($"{Username}:{Password}"));
            request.Headers[HttpRequestHeader.Authorization] = $"Basic {credentials}";

            using (StreamWriter writer = new StreamWriter(request.GetRequestStream()))
            {
                writer.Write(jsonPayload);
            }

            using (HttpWebResponse response = (HttpWebResponse)request.GetResponse())
            using (StreamReader reader = new StreamReader(response.GetResponseStream()))
            {
                string responseJson = reader.ReadToEnd();
                stopwatch.Stop();
                PerformanceProfiler.LogDatabaseOperation(queryLabel, (float)stopwatch.Elapsed.TotalMilliseconds, 1);
                UnityEngine.Debug.Log($"[DIAG][Neo4j] {queryLabel} success ms={stopwatch.Elapsed.TotalMilliseconds:F2}");
                //Debug.LogError($"[NEO4J][RESPONSE] {responseJson}");
                return responseJson;
            }
        }
        catch (WebException ex)
        {
            stopwatch.Stop();
            PerformanceProfiler.LogDatabaseOperation(queryLabel + "_FAIL", (float)stopwatch.Elapsed.TotalMilliseconds, 1);
            UnityEngine.Debug.LogError($"[DIAG][Neo4j] {queryLabel} failed ms={stopwatch.Elapsed.TotalMilliseconds:F2}");
            Debug.LogError($"Neo4j connection failed: {ex.Message}");
            if (ex.Response != null)
            {
                using var reader = new StreamReader(ex.Response.GetResponseStream());
                Debug.LogError("Error response: " + reader.ReadToEnd());
            }
            return "{}";
        }
    }

    private string GetQueryLabel(string query)
    {
        if (string.IsNullOrEmpty(query)) return "UnknownQuery";
        if (query.Contains("RETURN actorId")) return "CreateActorNode";
        if (query.Contains("RETURN measure_id")) return "CreateMeasureNode";
        if (query.Contains("CREATE (action:Action:Observing)")) return "BuildActionCreationQuery";
        if (query.Contains("durationNode:Time:Duration")) return "BuildDurationCalculationQuery";
        if (query.Contains("timeSpend:TimeSpend")) return "BuildTimeSpentOnObjectQuery";
        if (query.Contains("fixation:FixationCount")) return "BuildFixationCountQuery";
        if (query.Contains("TransitionsBetweenAOIs")) return "BuildTransitionCountBetweenAOIsQuery";
        if (query.Contains("transitions:Transitions")) return "BuildTransitionCountQuery";
        return "GenericQuery";
    }



    // ------------------------------------------------------------------------
    // Node Creation
    // ------------------------------------------------------------------------
    public string ExtractNodeID(string queryResponse)
    {
        if (string.IsNullOrEmpty(queryResponse))
        {
            Debug.LogWarning("[NEO4J] Empty JSON response when extracting node ID.");
            return "";
        }

        int startIndex = queryResponse.IndexOf("\"row\":") + 7;
        int endIndex = queryResponse.IndexOf("]", startIndex);

        return queryResponse.Substring(startIndex, endIndex - startIndex);
    }


    public string CreateActorNode(string recordingName, string stime)
    {
        string cypherQuery = $"CREATE (event:Event) " +
            $"WITH event, id(event) AS eventId SET event.name = 'Event_' + toString(eventId) " +
            $"WITH event, eventId MATCH (w:Environment {{name: 'HERE: Black in Rembrandt’s Time'}}) " +
            $"MERGE (w)-[:has_event]->(event) " +
            $"MERGE (a:Actor:User {{name: '{recordingName}', created_at:{stime}}}) WITH eventId, a, id(a) AS actorId, event " +
            $"MERGE (a)-[:participates_in]->(event) RETURN actorId";


        try
        {
            string queryResponse = Query(cypherQuery);
            Debug.LogError("query response: " + queryResponse);
            return ExtractNodeID(queryResponse);
        }
        catch (Exception ex)
        {
            Debug.LogError("Error while creating actor node: " + ex.Message);
            return null; // or handle it in a way suitable for your application
        }
    }

    public string CreateMeasureNode(string actorNodeID)
    {
        string cypherQuery = $"CREATE (m:Measure:Gaze) WITH m, id(m) AS measure_id MATCH (a:Actor) WHERE ID(a) = {actorNodeID} MERGE (a)-[:has_measures]->(m) RETURN measure_id";

        string queryResponse = Query(cypherQuery);
        Debug.LogError("query response: " + queryResponse);
        return ExtractNodeID(queryResponse);
    }

    // ------------------------------------------------------------------------
    // Action Creation
    // ------------------------------------------------------------------------

    public string BuildActionCreationQuery(string[] rowData, string actorNodeID)
    {
        //Debug.LogWarning("[DEBUG] rowData content: " + string.Join(",", rowData));
        //Debug.LogError("doing actionCreationQuery");
        //Debug.LogError($"[EYEDATA->NEO4J] Using ActorID={actorNodeID} when creating action");
        //Debug.LogError($"[EYEDATA->NEO4J] Parsed objectName={rowData[4]}, full={string.Join(",", rowData)}");
        
        string[] names = {
        "A1","A2","A3","B1","B2","B3","B4","B5",
        "C1","C2","C3","C4","C5","C6","D1","D2","D3","D4","D5"
    };

        string aoiName = "";
        string objectName = "";

        if (names.Contains(rowData[4].Substring(0, 2)))
        {
            aoiName = rowData[4].Substring(3);

            if (rowData[4].Contains("Painting"))
                aoiName = rowData[4].Substring(0, 2) + "_Background";

            if (rowData[4].Contains("Text"))
                aoiName = rowData[4].Substring(0, 2) + "_Text";

            objectName = rowData[4].Substring(0, 2);

            string cypherQuery = $@"
            CREATE (dbg:DebugMarker {{msg:'Unity reached Neo4j', time:timestamp()}})
            WITH dbg
            MERGE (obj:AOI {{name: '{aoiName}'}})
            MERGE (painting:Object:Painting {{objectName: '{objectName}'}})
            MERGE (modality:Modality:Gaze)
            MERGE (coordinates:Coordinates {{coordinates: '[{rowData[5]}]'}})
            MERGE (startTime:Time:StartTime {{startTime: '{rowData[0]}'}})
            MERGE (playerPositionCoordinates:Location {{coordinates: '[{rowData[1]}]'}})
            MERGE (distance:Distance {{distance: '[{rowData[3]}]'}})
            CREATE (action:Action:Observing)
            WITH obj, action, painting, modality, coordinates, startTime, playerPositionCoordinates, distance
            MATCH (actor:Actor) WHERE id(actor) = {actorNodeID}
            MATCH (actor)-[:participates_in]-(event:Event)
            MERGE (actor)-[:performs]->(action)
            MERGE (event)-[:has_actions]->(action)
            MERGE (action)-[:has_modality]->(modality)
            MERGE (action)-[:has_gaze_coordinates]->(coordinates)
            MERGE (action)-[:interacting_object]->(painting)
            MERGE (action)-[:interacting_AOI]->(obj)
            MERGE (action)-[:has_time]->(startTime)
            MERGE (action)-[:has_location]->(playerPositionCoordinates)
            MERGE (action)-[:has_distance_from_object]->(distance)
            RETURN action";

            //Debug.LogWarning("[DEBUG] Sending Cypher to Neo4j:\n" + cypherQuery);
            Debug.LogError($"[DEBUG][AOI] Raw: '{rowData[4]}' | objectName: '{objectName}' | aoiName: '{aoiName}'");

            return Query(cypherQuery);
        }

        return null;
    }


    // ------------------------------------------------------------------------
    // Metric Builders
    // ------------------------------------------------------------------------

    public string BuildDurationCalculationQuery(string actorNodeID)
    {
        string cypherQuery = $"MATCH (a:Actor)-[:performs]-(currentAction:Action:Observing)-[:has_time]-(currentStartTime:StartTime) WHERE ID(a) = {actorNodeID} WITH currentStartTime ORDER BY currentStartTime.startTime DESC LIMIT 2 WITH COLLECT(currentStartTime) AS startTimes WITH startTimes[0] AS currentStartTime, startTimes[1] AS previousStartTime WHERE previousStartTime IS NOT NULL MATCH (prevAction:Action:Observing)-[:has_time]->(previousStartTime) WITH prevAction, currentStartTime, previousStartTime, toFloat(currentStartTime.startTime) - toFloat(previousStartTime.startTime) AS duration CREATE (prevAction)-[:has_time]->(durationNode:Time:Duration {{duration: duration}}) RETURN prevAction, durationNode";


        return Query(cypherQuery);
    }

    public string BuildTimeSpentOnObjectQuery(string title, string objectName, string actorNodeID, string measureNodeID)
    {
        string cypherQuery = $"MATCH (actor:Actor)--(action:Action:Observing)--(object {{{title}: '{objectName}'}}) MATCH (action)--(duration:Time:Duration) WHERE ID(actor) = {actorNodeID} and duration.duration > 0.1 WITH SUM(toFloat(duration.duration)) AS totalTimeSpent, object MATCH (m:Measure) WHERE ID(m) = {measureNodeID} MERGE (m)-[:has_time_spend]->(timeSpend:TimeSpend)-[:related_to]-(object) ON CREATE SET timeSpend.timeSpendOnObject = totalTimeSpent ON MATCH SET timeSpend.timeSpendOnObject = totalTimeSpent";


        return Query(cypherQuery);
    }

    public string BuildFixationCountQuery(string title, string objectName, string actorNodeID, string measureNodeID)
    {
        string cypherQuery = $"MATCH (actor:Actor)--(action:Action:Observing)--(object {{{title}: '{objectName}'}})  MATCH (action)--(duration:Time:Duration) WHERE ID(actor) = {actorNodeID} and duration.duration > 0.1 MATCH (action)--(coordinates:Coordinates) WITH COUNT(DISTINCT coordinates) AS fixationCount, object MATCH (m:Measure) WHERE ID(m) = {measureNodeID} MERGE (m)-[:has_fixation_count]->(fixation:FixationCount)-[:related_to]-(object) ON CREATE SET fixation.fixationCount = fixationCount ON MATCH SET fixation.fixationCount = fixationCount";


        return Query(cypherQuery);

    }

    public string BuildTransitionCountQuery(string title, string objectName, string actorNodeID, string measureNodeID)
    {
        string cypherQuery = $"MATCH (actor:Actor)--(action:Action:Observing)--(object {{{title}: '{objectName}'}}) MATCH (action)--(duration:Time:Duration) WHERE ID(actor) = {actorNodeID} and duration.duration > 0.1 MATCH (action)--(startTime:StartTime) MATCH (action)--(coordinates:Coordinates) WITH startTime, coordinates, object ORDER BY startTime.startTime WITH COLLECT(coordinates) AS coordinatesList, object WITH REDUCE(s = 0, i IN RANGE(1, SIZE(coordinatesList) - 1) | CASE WHEN coordinatesList[i] <> coordinatesList[i - 1] THEN s + 1 ELSE s END) AS transitionCount, object MATCH (m:Measure) WHERE ID(m) = {measureNodeID} MERGE (m)-[:has_number_of_transitions]->(transitions:Transitions)-[:related_to]-(object) ON CREATE SET transitions.numberOfTransitions = transitionCount ON MATCH SET transitions.numberOfTransitions = transitionCount";


        return Query(cypherQuery);
    }

    public string BuildTransitionCountBetweenAOIsQuery(string objectName, string actorNodeID, string measureNodeID)
    {
        string cypherQuery = $"MATCH (actor:Actor)--(action:Action:Observing)--(object {{objectName: '{objectName}'}}) MATCH (action)--(duration:Time:Duration) WHERE ID(actor) = {actorNodeID} and duration.duration > 0.1 MATCH (action)--(startTime:StartTime) MATCH (action)--(coordinates:AOI) WITH startTime, coordinates, object ORDER BY startTime.startTime WITH COLLECT(coordinates) AS coordinatesList, object WITH REDUCE(s = 0, i IN RANGE(1, SIZE(coordinatesList) - 1) | CASE WHEN coordinatesList[i] <> coordinatesList[i - 1] THEN s + 1 ELSE s END) AS transitionCount, object MATCH (m:Measure) WHERE ID(m) = {measureNodeID} MERGE (m)-[:has_number_of_transitions]->(transitions:TransitionsBetweenAOIs)-[:related_to]-(object) ON CREATE SET transitions.numberOfTransitions = transitionCount ON MATCH SET transitions.numberOfTransitions = transitionCount";


        return Query(cypherQuery);
    }
}
