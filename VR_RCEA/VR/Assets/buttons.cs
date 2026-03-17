using System.Collections.Generic;
using UnityEngine;
using Valve.VR;
using UnityEngine.UI;
using System.IO;
using System.Net;
//using Neo4j.Driver;
//using Neo4jClient;


public class buttons : MonoBehaviour
{
    public GameObject button;
    public GameObject Panel;
   
    public Text titleText;
    public Text creatorText;
    public Text descriptionText;
    public Text exhibitText;
    public Text onMaterialText;
    public Text genreText;
    public Text collectionText;

    //public float x;
    //public float y;
    //public float z;

    public static string Username = "neo4j";
    public static string Password = "1234";
    public static string IP = "localhost:7474";
    public static bool DebugLog = false;
    public static int Limit = 0;

    public SteamVR_Action_Boolean m_InteractUI = SteamVR_Input.GetBooleanAction("InteractUI");

    public void PanelOpener()
    {
        if (Panel != null)
        {
            try
            {

                if (button != null)
                {
                    string Query = "";
                    string Query2 = "";

                    //Panel.GetComponent<RectTransform>().anchoredPosition = new Vector3(x, y, z);

                    //11.370f, -0.8f, 2.584f

                    bool isActive = Panel.activeSelf;
                    Panel.SetActive(!isActive);

                    
                    if (button.name == "A1-button")
                    {
                        Query = "MATCH (n:Paintings {name:'Map of Paranambucae'}) return n";

                        Query2 = "MATCH (n:Paintings {name:'Map of Paranambucae'})-[r]-(b) return type(r),b.name,b.description";
                    }
                    if (button.name == "A2-button")
                    {
                        Query = "MATCH (n:Paintings {name:'Head of a Boy'}) return n";

                        Query2 = "MATCH (n:Paintings {name:'Head of a Boy'})-[r]-(b) return type(r),b.name,b.description";
                    }
                    if (button.name == "A3-button")
                    {
                        Query = "MATCH (n:Paintings {name:'The Market in Dam Square'}) return n";

                        Query2 = "MATCH (n:Paintings {name:'The Market in Dam Square'})-[r]-(b) return type(r),b.name,b.description";
                    }
                    if (button.name == "B1-button")
                    {
                        Query = "MATCH (n:Paintings {name:'Diego Bemba, a Servant of Don Miguel de Castro'}) return n";

                        Query2 = "MATCH (n:Paintings {name:'Diego Bemba, a Servant of Don Miguel de Castro'})-[r]-(b) return type(r),b.name,b.description";
                    }
                    if (button.name == "B2-button")
                    {
                        Query = "MATCH (n:Paintings {name:'Don Miguel de Castro, Emissary of Congo'}) return n";

                        Query2 = "MATCH (n:Paintings {name:'Don Miguel de Castro, Emissary of Congo'})-[r]-(b) return type(r),b.name,b.description";
                    }
                    if (button.name == "B3-button")
                    {
                        Query = "MATCH (n:Paintings {name:'Pedro Sunda, a Servant of Don Miguel de Castro'}) return n";

                        Query2 = "MATCH (n:Paintings {name:'Pedro Sunda, a Servant of Don Miguel de Castro'})-[r]-(b) return type(r),b.name,b.description";
                    }
                    if (button.name == "C1-button")
                    {
                        Query = "MATCH (n:Paintings {name:'Man in a Turban'}) return n";

                        Query2 = "MATCH (n:Paintings {name:'Man in a Turban'})-[r]-(b) return type(r),b.name,b.description";
                    }
                    if (button.name == "C2-button")
                    {
                        Query = "MATCH (n:Paintings {name:'Portrait of a Black Girl'}) return n";

                        Query2 = "MATCH (n:Paintings {name:'Portrait of a Black Girl'})-[r]-(b) return type(r),b.name,b.description";
                    }
                    if (button.name == "C3-button")
                    {
                        Query = "MATCH (n:Paintings {name:'Portrait of a Man'}) return n";

                        Query2 = "MATCH (n:Paintings {name:'Portrait of a Man'})-[r]-(b) return type(r),b.name,b.description";
                    }
                    if (button.name == "C4-button")
                    {
                        Query = "MATCH (n:Paintings {name:'Two moors'}) return n";

                        Query2 = "MATCH (n:Paintings {name:'Two moors'})-[r]-(b) return type(r),b.name,b.description";

                    }
                    if (button.name == "C5-button")
                    {
                        Query = "MATCH (n:Paintings {name:'Head of a Boy in a Turban'}) return n";

                        Query2 = "MATCH (n:Paintings {name:'Head of a Boy in a Turban'})-[r]-(b) return type(r),b.name,b.description";

                    }
                    if (button.name == "C6-button")
                    {
                        Query = "MATCH (n:Paintings {name:'King Caspar'}) return n";

                        Query2 = "MATCH (n:Paintings {name:'King Caspar'})-[r]-(b) return type(r),b.name,b.description";

                    }
                    if (button.name == "D1-button")
                    {
                        Query = "MATCH (n:Paintings {name:'The New Utopia Begins Here: Hermina Huiswoud'}) return n";

                        Query2 = "MATCH (n:Paintings {name:'The New Utopia Begins Here: Hermina Huiswoud'})-[r]-(b) return type(r),b.name,b.description";

                    }
                    if (button.name == "D2-button")
                    {
                        Query = "MATCH (n:Paintings {name:'The Unspoken Truth'}) return n";

                        Query2 = "MATCH (n:Paintings {name:'The Unspoken Truth'})-[r]-(b) return type(r),b.name,b.description";

                    }
                    if (button.name == "D3-button")
                    {
                        Query = "MATCH (n:Paintings {name:'Ilona'}) return n";

                        Query2 = "MATCH (n:Paintings {name:'Ilona'})-[r]-(b) return type(r),b.name,b.description";

                    }

                    if (Query != "")
                    {
                        

                        var wreq = WebRequest.Create("http://" + IP + "/db/data/transaction/commit");
                        wreq.Method = "POST";
                        wreq.ContentType = "application/json";
                        wreq.Credentials = new NetworkCredential(Username, Password);

                        var requestStream = new StreamWriter(wreq.GetRequestStream());

                        requestStream.Write("{\"statements\" : [ { \"statement\" : \"" + Query + "\"} ]}");

                        requestStream.Flush();
                        requestStream.Close();

                       
                        var wres = (HttpWebResponse)wreq.GetResponse();
                        
                        var stream = wres.GetResponseStream();
                        var streamReader = new StreamReader(stream);
                        var responseJson = streamReader.ReadToEnd();

                       
                        Node res = JsonUtility.FromJson<Node>(responseJson);


                        titleText.text = res.results[0].data[0].row[0].name;
                        descriptionText.text = res.results[0].data[0].row[0].description;
                        exhibitText.text = res.results[0].data[0].row[0].exhibit;
                        
                        streamReader.Close();
                        stream.Close();


                        wreq = WebRequest.Create("http://" + IP + "/db/data/transaction/commit");
                        wreq.Method = "POST";
                        wreq.ContentType = "application/json";
                        wreq.Credentials = new NetworkCredential(Username, Password);

                        requestStream = new StreamWriter(wreq.GetRequestStream());

                        requestStream.Write("{\"statements\" : [ { \"statement\" : \"" + Query2 + "\"} ]}");

                        requestStream.Flush();
                        requestStream.Close();

                        wres = (HttpWebResponse)wreq.GetResponse();
                      
                        stream = wres.GetResponseStream();
                        streamReader = new StreamReader(stream);
                        responseJson = streamReader.ReadToEnd();

                        Node2 res2 = JsonUtility.FromJson<Node2>(responseJson);

                        var rows = res2.results[0].data;
                        foreach (var item in rows)
                        {
                            if (item.row[0] == "on_MATERIAL")
                            {
                                if (onMaterialText.text != "OnMaterialText" & onMaterialText.text != item.row[1])
                                {
                                    onMaterialText.text = onMaterialText.text+", "+item.row[1];
                                }
                                else { onMaterialText.text = item.row[1]; }
                            }
                            if (item.row[0] == "has_Creator")
                            {
                                creatorText.text = item.row[1];
                            }
                            if (item.row[0] == "in_COLLECTION")
                            {
                                collectionText.text = item.row[1];
                            }
                            if (item.row[0] == "belongsto_GENRE")
                            {
                                genreText.text = item.row[1];
                            }
                        }

                        streamReader.Close();
                        stream.Close();
                    }
                }


            }
            catch (WebException webex)
            {
                UnityEngine.Debug.LogError("neo4j connection failed.\nReason:" + webex.Message);
            }

        }
    }

    public void PanelCloser()
    {
        if (Panel != null)
        {
            Panel.SetActive(false);
        }
    }

    [System.Serializable]
    public class Node
    {
        public List<Result> results;
        public List<object> errors;
    }

    [System.Serializable]
    public class Result
    {
        public List<string> columns;
        public List<Rows> data;
    }


    [System.Serializable]
    public class Rows
    {
        public List<NodeData> row;
    }


    [System.Serializable]
    public class NodeData
    {
        public string name;
        public string exhibit;
        public string description;
    }


    [System.Serializable]
    public class Node2
    {
        public List<Result2> results;
        public List<object> errors;
    }

    [System.Serializable]
    public class Result2
    {
        public List<string> columns;
        public List<Rows2> data;
    }


    [System.Serializable]
    public class Rows2
    {
        public List<string> row;
        public List<string> meta;
    }





}


