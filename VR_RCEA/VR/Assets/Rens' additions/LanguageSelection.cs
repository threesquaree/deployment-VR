using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using TMPro;

public class LanguageSelection : MonoBehaviour
{
    [SerializeField] List<Language> languages;
    [SerializeField] Dropdown dropdown;
    [SerializeField] List<TextMeshProUGUI> textFields;

    private void Start()
    {
        dropdown.ClearOptions();

        List<string> lans = new List<string>();
        
        foreach(var lan in languages)
        {
            lans.Add(lan.language);
        }

        dropdown.AddOptions(lans);

        SelectLanguage();
    }

    public void SelectLanguage()
    {
        var inputLanguage = languages[dropdown.value].inputText;

        for (int i = 0; i < textFields.Count; i++)
        {
            textFields[i].text = inputLanguage[i];
        }

        Debug.Log("Language applied!");
    }
}
