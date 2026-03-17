using UnityEngine;

[CreateAssetMenu(menuName = "Picture Object (Data)")]
public class PictureObject : ScriptableObject
{
    public string title;
    public string description;
    public Sprite picture;
}