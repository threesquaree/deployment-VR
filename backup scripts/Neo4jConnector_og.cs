using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Text;
using UnityEngine;
using System.Collections;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.UI;
using UnityEngine.Windows.Speech;
using Newtonsoft.Json;



public class Neo4jConnector
{
    public string Username = "neo4j";
    public string Password = "12345678";
    public string IP = "localhost";
    public int Port = 7474;
    public bool DebugLog = true;
    public int Limit = 0;
	
	
	public string Query(string query)
	{
		try
		{
			// Construct the URL for the transaction endpoint
			string url = $"http://{IP}:{Port}/db/neo4j/tx/commit"; // Adjust URL based on Neo4j version

			// Create the web request
			HttpWebRequest request = (HttpWebRequest)WebRequest.Create(url);
			request.Method = "POST";

			// Set basic authentication credentials
			string credentials = Convert.ToBase64String(System.Text.Encoding.ASCII.GetBytes($"{Username}:{Password}"));
			request.Headers[HttpRequestHeader.Authorization] = $"Basic {credentials}";
			request.ContentType = "application/json";

			// Construct the JSON payload
			string jsonPayload = "{\"statements\" : [ { \"statement\" : \"" + query.Replace("\"", "\\\"") + "\" } ]}";
			
			// Write JSON payload to request stream
			using (StreamWriter streamWriter = new StreamWriter(request.GetRequestStream()))
			{
				streamWriter.Write(jsonPayload);
				streamWriter.Flush();
			}

			// Get the response
			using (HttpWebResponse response = (HttpWebResponse)request.GetResponse())
			using (Stream responseStream = response.GetResponseStream())
			using (StreamReader streamReader = new StreamReader(responseStream))
			{
				string responseJson = streamReader.ReadToEnd();

				if (DebugLog)
				{
					Debug.Log("Response Headers:\n" + response.Headers);
					Debug.Log("Response Json:" + responseJson);
				}
				
				//Debug.LogError(responseJson);
				return responseJson;
			}
		}
		catch (WebException webex)
		{
			Debug.LogError("Neo4j connection failed.\nReason:" + webex.Message);
			if (webex.Response != null)
			{
				using (var errorResponse = (HttpWebResponse)webex.Response)
				using (var errorStream = errorResponse.GetResponseStream())
				using (var reader = new StreamReader(errorStream))
				{
					Debug.LogError("Error response: " + reader.ReadToEnd());
				}
			}
			return "{}";
		}
	}

	
	public string CreateNode(string nodeType, string nodeValue)
    {
        string query = "CREATE (n:"+nodeType+" n.nodeValue = "+nodeValue+") RETURN ID(n)";
		
        return query;
    }
	
	
	public string CreateActorNode(string recordingName, string stime)
	{
		string cypherQuery = $"CREATE (event:Event) WITH event, id(event) AS eventId SET event.name = 'Event_' + toString(eventId) WITH event, eventId MATCH (w:Environment {{name: 'HERE: Black in Rembrandt’s Time'}}) MERGE (w)-[:has_event]->(event) MERGE (a:Actor:User {{name: '{recordingName}', created_at:{stime}}}) WITH eventId, a, id(a) AS actorId, event MERGE (a)-[:participates_in]->(event) RETURN actorId";


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
	
	public string ExtractNodeID(string queryResponse)
    {
        int startIndex = queryResponse.IndexOf("\"row\":") + 7;
        int endIndex = queryResponse.IndexOf("]", startIndex);
        
        return queryResponse.Substring(startIndex, endIndex - startIndex);
    }

	
	public string BuildActionCreationQuery(string[] rowData, string actorNodeID)
    {
		string[] names = {
			"A1", "A2", "A3", "B1",
			"B2", "B3", "B4", "B5",
			"C1", "C2", "C3", "C4",
			"C5", "C6", "D1", "D2",
			"D3", "D4", "D5"
		};

		string aoiName = "";
		string objectName = ""; // Initialize objectName for later use.

		// Check if the first two characters of rowData[2] exist in names array.
		if (names.Contains(rowData[2].Substring(0, 2)))
		{
			// If rowData[2] contains "Painting", set aoiName to "Background".
			aoiName = rowData[2].Substring(3); // Extract substring starting from index 2.
			if (rowData[2].Contains("Painting"))
			{
				aoiName = rowData[2].Substring(0, 2)+"_Background";
			}
			if (rowData[2].Contains("Text"))
			{
				aoiName = rowData[2].Substring(0, 2)+"_Text";
			}
			// Set objectName to the first two characters of rowData[2].
			objectName = rowData[2].Substring(0, 2);
			
			// changed query
			//string cypherQuery = $"MERGE (obj:AOI {{name: '{aoiName}'}}) MERGE (painting:Object:Painting {{objectName: '{objectName}'}}) MERGE (modality:Modality:Gaze) MERGE (coordinates:Coordinates {{coordinates: '[{rowData[5]}]'}}) MERGE (startTime:Time:StartTime {{startTime: {rowData[0]}}}) MERGE (playerPositionCoordinates:Location {{coordinates: '[{rowData[1]}]'}}) MERGE (distance:Distance {{distance: {rowData[3]}}}) CREATE (action:Action:Observing) WITH obj, action, painting, modality, coordinates, startTime, playerPositionCoordinates, distance MATCH (actor:Actor) WHERE id(actor) = {actorNodeID} MATCH (actor)-[:participates_in]-(event:Event) MERGE (actor)-[:performs]->(action) MERGE (event)-[:has_actions]->(action) MERGE (action)-[:has_modality]->(modality) MERGE (action)-[:has_gaze_coordinates]->(coordinates) MERGE (action)-[:interacting_object]->(painting) MERGE (action)-[:interacting_AOI]->(obj) MERGE (action)-[:has_time]->(startTime) MERGE (action)-[:has_location]->(playerPositionCoordinates) MERGE (action)-[:has_distance_from_object]->(distance) RETURN action";
			string cypherQuery = $"MERGE (obj:AOI {{name: '{aoiName}'}}) " +
                $"MERGE (painting:Object:Painting {{objectName: '{objectName}'}}) " +
                $"MERGE (modality:Modality:Gaze) " +
                $"MERGE (coordinates:Coordinates {{coordinates: '[{rowData[5]}]'}}) " +
                $"MERGE (startTime:Time:StartTime {{startTime: '{rowData[0]}'}}) " +
                $"MERGE (playerPositionCoordinates:Location {{coordinates: '[{rowData[1]}]'}}) " +
                $"MERGE (distance:Distance {{distance: '[{rowData[3]}]'}}) " +
                $"CREATE (action:Action:Observing) " +
                $"WITH obj, action, painting, modality, coordinates, startTime, playerPositionCoordinates, distance " +
                $"MATCH (actor:Actor) WHERE id(actor) = {actorNodeID}" +
                $"MATCH (actor)-[:participates_in]-(event:Event) " +
                $"MERGE (actor)-[:performs]->(action) " +
                $"MERGE (event)-[:has_actions]->(action) " +
                $"MERGE (action)-[:has_modality]->(modality) " +
                $"MERGE (action)-[:has_gaze_coordinates]->(coordinates) " +
                $"MERGE (action)-[:interacting_object]->(painting) " +
                $"MERGE (action)-[:interacting_AOI]->(obj) " +
                $"MERGE (action)-[:has_time]->(startTime) " +
                $"MERGE (action)-[:has_location]->(playerPositionCoordinates) " +
                $"MERGE (action)-[:has_distance_from_object]->(distance) " +
                $"RETURN action";

			return Query(cypherQuery);
		}
		
        

        return null;
        
		//Debug.LogError(cypherQuery);
        
        
    }
    
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
