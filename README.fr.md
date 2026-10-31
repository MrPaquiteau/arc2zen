# arc2zen

**Passez d'[Arc](https://arc.net) à [Zen](https://zen-browser.app) en une seule commande.**
Espaces, onglets épinglés, dossiers, favoris, signets, historique complet, mots de passe, cookies
(vous restez connecté), extensions et réglages.

[English](README.md)

```sh
bash -c "$(curl -fsSL https://raw.githubusercontent.com/MrPaquiteau/arc2zen/v0.1.0/run.sh)"
```

Rien à installer et aucune dépendance : il suffit de Python 3, fourni avec les outils en ligne de
commande de macOS.

---

## Ce qui est migré

| Depuis Arc | Vers Zen | Import intégré de Zen | arc2zen |
|---|---|:-:|:-:|
| Espaces (nom, emoji, couleurs) | Espaces | ✅ | ✅ |
| Onglets épinglés, dossiers, sous-dossiers | Onglets épinglés et dossiers | ⚠️ ordre inversé dans tous les espaces sauf le premier | ✅ ordre d'Arc |
| Noms donnés aux onglets épinglés | Noms des onglets | ❌ titres des pages | ✅ |
| Icônes des sites | Icônes des épingles et des Essentials | ❌ | ✅ |
| Favoris | Essentials | ✅ | ✅ |
| Onglets ouverts de chaque espace | Onglets dans l'espace correspondant | ❌ | ✅ |
| Profils Arc | Conteneurs Zen | ✅ | ✅ |
| Signets | Signets | ✅ | ✅ (conservés en signets) |
| Historique | Historique | ⚠️ 180 derniers jours, 2 000 pages max | ✅ en entier |
| Mots de passe, cartes, données de formulaire | Idem | ✅ | ✅ |
| **Cookies** (rester connecté partout) | Cookies | ❌ | ✅ |
| Sessions protégées de la purge anti-pistage de Firefox | | ❌ | ✅ (voir plus bas) |
| **Extensions** | Leur version Firefox, avec le même état actif/inactif et les mêmes permissions | ❌ | ✅ |
| Moteur par défaut et recherches de site (`@gmail`, `@github`…) | Moteurs de recherche | ❌ | ✅ |
| Permissions par site (caméra, notifications, localisation…) | Idem | ❌ | ✅ |
| Zoom par site, dossier de téléchargement, langues | Idem | ❌ | ✅ |

Si votre Zen intègre un importeur Arc (Zen 1.2x et plus récent), arc2zen s'en sert pour les espaces
afin de rester fidèle au format de Zen. Il corrige ensuite l'ordre et les noms, puis ajoute tout ce
que cet importeur ne gère pas.

**Non migré :** les Boosts, les Easels et Notes, le routage vers Little Arc, les onglets archivés
(ils restent dans l'historique), les raccourcis clavier personnalisés (listés à la fin pour que vous
puissiez les recréer), et les extensions qui n'existent pas pour Firefox.

## Utilisation

1. Installez [Zen](https://zen-browser.app/download) et ouvrez-le une première fois.
2. Lancez la commande ci-dessus, ou clonez le dépôt et lancez `./arc2zen`.
3. arc2zen affiche ce qu'il a trouvé dans Arc et demande confirmation avant de modifier quoi que
   ce soit.
4. **Quand macOS demande d'autoriser Zen à utiliser « Arc Safe Storage »**, tapez le mot de passe
   de votre Mac et cliquez sur **Autoriser**. Une fois suffit : inutile de choisir *Toujours
   autoriser* (voir [la fenêtre du trousseau](#la-fenêtre-du-trousseau-macos)).
5. Zen redémarre avec tout dedans.

Vous pouvez laisser Arc ouvert : il est seulement lu, jamais modifié. Toutes les options sont
décrites dans le [README anglais](README.md#how-to-use-it), par exemple `--dry-run`, `--only`,
`--skip` ou `--export`. Relancer l'outil ne crée pas de doublons.

## Sécurité et vie privée

- **Sauvegarde d'abord.** Votre profil Zen est copié dans
  `~/Library/Application Support/zen-arc2zen-backups/` avant toute modification.
- **Rien ne quitte votre Mac.** Les seuls appels réseau vont vers `addons.mozilla.org`, pour trouver
  et télécharger les extensions.
- **Pilotage local uniquement, le temps de la migration.** Voir
  [le mode migration](#le-mode-migration-marionette) pour savoir exactement ce qui est ouvert, quand
  et à qui.
- **Versions figées.** La commande ci-dessus lance une version publiée (`v0.1.0`), jamais ce qui se
  trouve sur `main` à ce moment-là.
- **Extensions :** une extension n'est installée que si elle figure dans la liste fournie (vérifiée
  sur addons.mozilla.org), dans la correspondance officielle Chrome→Firefox de Mozilla, ou si son
  nom correspond exactement à une extension **mise en avant par Mozilla**. Jamais de copie publiée
  par un inconnu.

### Le mode migration (Marionette)

Pour passer par les API de Zen plutôt que d'écrire dans ses bases de données, arc2zen démarre Zen avec
Marionette, le protocole d'automatisation intégré à Firefox, avec l'accès système activé. Ce qui pilote
Zen dans ce mode peut y exécuter du code privilégié, donc faire tout ce que Zen peut faire : lire ses
mots de passe et ses cookies, lire et écrire vos fichiers, lancer des programmes. Voici exactement
quand, et à qui, c'est ouvert :

- **Quand :** uniquement pendant la migration. Cela commence à l'étape *Starting Zen in migration
  mode* et se termine quand arc2zen quitte Zen à l'étape *Saving and restarting Zen*, en général
  quelques minutes plus tard. Zen est ensuite rouvert normalement, sans Marionette, et arc2zen
  n'enregistre aucun réglage qui pourrait le réactiver. Une icône de robot s'affiche dans la barre
  d'adresse tant que ce mode est actif.
- **À qui :** seulement aux programmes qui tournent sur ce Mac. Marionette écoute sur
  `127.0.0.1:2828`, jamais sur le réseau. Il n'accepte qu'une session, qu'arc2zen ouvre quelques
  secondes après le démarrage de Zen, et refuse toute autre connexion jusqu'à la fin. Si un autre
  programme passait avant, arc2zen ne pourrait pas se connecter : il s'arrête et vous demande de
  quitter Zen.
- **Si arc2zen est interrompu** (Ctrl-C, terminal fermé, `kill`), il quitte Zen avant de s'arrêter.
  Seul un arrêt forcé (`kill -9`, un plantage) peut laisser Zen en mode migration. Si vous voyez
  l'icône de robot en dehors d'une migration, quittez Zen (⌘Q) et rouvrez-le.

### La fenêtre du trousseau macOS

Arc ne garde pas vos mots de passe et cookies en clair. Il les chiffre avec une clé secrète rangée
dans le **trousseau de session** de votre Mac, sous le nom **« Arc Safe Storage »**. Pour les
importer, Zen doit lire cette clé, et macOS la protège : toute app autre qu'Arc doit d'abord vous
demander la permission. C'est cette fenêtre.

- **Autoriser** donne l'accès cette fois-ci. arc2zen ne lit la clé qu'une fois par exécution, cela
  suffit donc. **Toujours autoriser** permettrait à Zen de la relire sans rien demander à l'avenir,
  ce qui est inutile.
- **Refuser** : arc2zen saute les mots de passe et les cookies, tout le reste est quand même migré.
  Pour éviter la fenêtre, lancez `arc2zen --skip passwords,cookies`.
- **Vos mots de passe iCloud (app Mots de passe) ne sont pas concernés.** Ils sont dans le Trousseau
  iCloud, que ni Zen ni arc2zen ne lisent. Seuls les mots de passe enregistrés par Arc sont importés.
- La clé et les mots de passe déchiffrés ne sortent jamais de Zen. arc2zen ne voit que des
  comptages. Une fois importés, Zen garde vos mots de passe dans son propre coffre chiffré. Vous
  pouvez le protéger par un mot de passe principal (Zen → Réglages → Vie privée et sécurité).

**Vous avez cliqué sur « Toujours autoriser » par erreur ?** Ouvrez *Trousseau d'accès*, cherchez
*Arc Safe Storage*, double-cliquez dessus, allez dans l'onglet *Contrôle d'accès*, sélectionnez
**Zen**, cliquez sur **−** puis sur *Enregistrer les modifications*. Gardez Arc dans la liste.

### Pourquoi mes sessions restent-elles ouvertes ?

Firefox (et donc Zen) supprime régulièrement les
cookies des sites qu'il considère comme traqueurs, comme Google, YouTube, LinkedIn ou Instagram, si
vous ne les avez jamais utilisés dans *ce* navigateur. arc2zen enregistre pour les sites de votre
historique Arc une interaction, comme le ferait une vraie visite. Elle dure 45 jours et se renouvelle
à chaque visite.

## Windows

Pas encore pris en charge, mais c'est prévu. Les contributions sont les bienvenues, voir la section
[Windows](README.md#windows).

## Licence

MIT. Projet indépendant, sans lien avec The Browser Company ni l'équipe de Zen.
