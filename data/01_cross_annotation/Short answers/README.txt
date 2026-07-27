VALIDATION DES RÉPONSES COURTES

Source attendue : feuille 'Short answer'
Nombre total d'items : 296
Revue primaire : 100 % des items
Pourcentage demandé en second contrôle : 20 %
Items effectivement double-contrôlés : 59 (19.93 %)
Nombre total de jugements : 355
Nombre d'annotateurs : 9

Structure créée :
- annotateurs/ : un fichier Excel par annotateur, avec une feuille LEGEND détaillée.
- admin/gold_reference.xlsx : copie de référence de toutes les colonnes sources.
- admin/assignment_manifest.xlsx : détail de chaque attribution primaire et secondaire.
- admin/double_check_sample.xlsx : liste exacte des items sélectionnés pour la fiabilité.
- admin/allocation_summary.xlsx : charge par annotateur, axe, difficulté et strate.
- admin/annotation_codebook.xlsx : copie administrative du guide.

Méthode :
- Tous les items sont traités comme documentés.
- Chaque item reçoit un reviewer primaire.
- Un échantillon reproductible est sélectionné proportionnellement par Axe × Difficulty.
- Chaque item de l'échantillon reçoit un second reviewer différent du premier.
- Le tirage est reproductible grâce à la graine aléatoire configurée.

Colonnes d'évaluation :
- answer_correctness : correct / minor_fix / incorrect
- question_quality : ok / review
- accepted_variants : variantes correctes séparées par |
- supporting_source : source vérifiable
- review_comment : obligatoire en cas de problème

Aucune colonne de créateur n'est configurée : le script équilibre les attributions mais ne peut pas identifier l'auteur initial d'un item.
