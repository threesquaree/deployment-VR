using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using System.IO;
using System.Net;

public class moreInfoButton : MonoBehaviour
{
    public GameObject Panel;
    public GameObject mainPanel;
    public Text text;
    public Text titleText;
    public Text descriptionText;
    public static string Username = "neo4j";
    public static string Password = "1234";
    public static string IP = "localhost:7474";
    public static bool DebugLog = false;
    public static int Limit = 0;
    public void PanelOpener()
    {
        if (Panel != null)
        {
            try
            {
                var pos = mainPanel.GetComponent<RectTransform>().anchoredPosition;
                
                float x = (pos.x) + 0.13f;
                float y = (pos.y) + 0.7f;
                

                Panel.GetComponent<RectTransform>().anchoredPosition = new Vector2(x,y);


                //11.5f, -0.1f, 2.584f

                if (text.text != "collectionText" & text.text != "GenreText" & text.text != "CreatorText" & text.text != "OnMaterialText")
                {

                    bool isActive = Panel.activeSelf;
                    Panel.SetActive(!isActive);

                    var Query = "MATCH (n {name:'" + text.text + "'}) return n";


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

                    streamReader.Close();
                    stream.Close();
                }
                else {
                    Panel.SetActive(false);
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
        public string description;
    }

}
