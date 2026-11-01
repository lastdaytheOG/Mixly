import json
import os

from mixly.games import epic_games, parse_pairs, steam_games, steam_libraries
from tests.helpers import TempCase


class SteamTests(TempCase):
    def setUp(self):
        super().setUp()
        self.other = self.path("Other Library")
        folders = f'"libraryfolders"\n{{\n\t"0"\n\t{{\n\t\t"path"\t\t"{self.other.replace(chr(92), chr(92) * 2)}"\n\t}}\n}}\n'
        self.write("Steam/steamapps/libraryfolders.vdf", folders)
        self.add_game(self.path("Steam"), "10", "Counter Thing", "counter")
        self.add_game(self.other, "20", "Other Game", "other game")

    def add_game(self, library, appid, name, folder):
        manifest = f'"AppState"\n{{\n\t"appid"\t\t"{appid}"\n\t"name"\t\t"{name}"\n\t"installdir"\t\t"{folder}"\n}}\n'
        relative = os.path.relpath(os.path.join(library, "steamapps", f"appmanifest_{appid}.acf"), self.base)
        self.write(relative, manifest)
        self.write(os.path.relpath(os.path.join(library, "steamapps", "common", folder, "game.exe"), self.base))

    def test_parses_escaped_paths(self):
        self.assertEqual(parse_pairs('"path"  "D:\\\\Games"'), [("path", r"D:\Games")])

    def test_reads_every_library(self):
        self.assertEqual(steam_libraries(self.path("Steam")), [self.path("Steam"), self.other])

    def test_finds_games_in_every_library(self):
        games = {game.id: game for game in steam_games(self.path("Steam"))}
        self.assertEqual(games["steam:10"].name, "Counter Thing")
        self.assertEqual(games["steam:10"].source, self.path("Steam", "steamapps", "common", "counter"))
        self.assertEqual(games["steam:20"].source, os.path.join(self.other, "steamapps", "common", "other game"))
        self.assertIn("steam.exe", games["steam:10"].processes)

    def test_skips_a_manifest_with_no_folder_on_disk(self):
        self.write("Steam/steamapps/appmanifest_30.acf", '"installdir" "missing"')
        self.assertNotIn("steam:30", {game.id for game in steam_games(self.path("Steam"))})


class EpicTests(TempCase):
    def add(self, name, **values):
        self.write(f"manifests/{name}.item", json.dumps(values))

    def test_finds_installed_games(self):
        self.write("games/Fort/game.exe")
        self.add("a", DisplayName="Fort", AppName="fort", InstallLocation=self.path("games", "Fort"))
        games = epic_games(self.path("manifests"))
        self.assertEqual([(game.id, game.name, game.source) for game in games], [("epic:fort", "Fort", self.path("games", "Fort"))])

    def test_skips_incomplete_and_broken_manifests(self):
        self.write("games/Half/game.exe")
        self.add("a", DisplayName="Half", InstallLocation=self.path("games", "Half"), bIsIncompleteInstall=True)
        self.write("manifests/b.item", "not json")
        self.assertEqual(epic_games(self.path("manifests")), [])
