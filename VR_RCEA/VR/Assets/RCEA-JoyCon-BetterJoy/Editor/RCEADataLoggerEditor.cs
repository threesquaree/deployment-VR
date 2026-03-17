#if UNITY_EDITOR
using UnityEditor;
using UnityEngine;

[CustomEditor(typeof(RCEADataLogger))]
public class RCEADataLoggerEditor : Editor
{
    static bool startOnApply = true;     // Start logging after Apply Now
    static bool splitIfChanged = false;  // Start a NEW file if ID changed while logging

    public override void OnInspectorGUI()
    {
        DrawDefaultInspector();

        EditorGUILayout.Space(8);
        EditorGUILayout.LabelField("Participant Controls", EditorStyles.boldLabel);

        startOnApply  = EditorGUILayout.ToggleLeft("Start logging on Apply", startOnApply);
        splitIfChanged = EditorGUILayout.ToggleLeft("Split file if ID changed (while logging)", splitIfChanged);

        using (new EditorGUI.DisabledScope(!Application.isPlaying))
        {
            if (GUILayout.Button("Apply Now"))
            {
                var logger = (RCEADataLogger)target;
                logger.ApplyParticipantNow(startOnApply, splitIfChanged);
                EditorUtility.SetDirty(target);
            }
        }

        if (!Application.isPlaying)
        {
            EditorGUILayout.HelpBox("Enter the participant ID, press Play, then click 'Apply Now'.", MessageType.Info);
        }
    }
}
#endif
