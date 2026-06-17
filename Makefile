.PHONY: build run clean icon test capture

APP_NAME = RadioBar
BUILD_DIR = build
APP_BUNDLE = $(BUILD_DIR)/$(APP_NAME).app
SOURCES = Sources/main.swift Sources/Station.swift Sources/MetadataParser.swift Sources/RadioPlayer.swift Sources/AppDelegate.swift Sources/ArtworkFetcher.swift Sources/GlobalHotkey.swift Sources/TrackClassifier.swift
ICONSET = $(BUILD_DIR)/AppIcon.iconset
ICNS = $(BUILD_DIR)/AppIcon.icns

build: $(APP_BUNDLE)/Contents/MacOS/$(APP_NAME) $(APP_BUNDLE)/Contents/Resources/AppIcon.icns

$(APP_BUNDLE)/Contents/MacOS/$(APP_NAME): $(SOURCES) Info.plist
	@mkdir -p $(APP_BUNDLE)/Contents/{MacOS,Resources}
	@cp Info.plist $(APP_BUNDLE)/Contents/Info.plist
	swiftc -o $@ -framework AppKit -framework AVFoundation -framework Carbon $(SOURCES)
	@echo "→ Built binary"

$(ICNS): gen_icon.swift
	@rm -rf $(ICONSET)
	swift gen_icon.swift $(ICONSET)
	iconutil -c icns $(ICONSET) -o $(ICNS)
	@echo "→ Built icon"

$(APP_BUNDLE)/Contents/Resources/AppIcon.icns: $(ICNS)
	@mkdir -p $(APP_BUNDLE)/Contents/Resources
	cp $(ICNS) $(APP_BUNDLE)/Contents/Resources/AppIcon.icns
	touch $(APP_BUNDLE)

icon: $(ICNS)

run: build
	open $(APP_BUNDLE)

capture:
	@mkdir -p $(BUILD_DIR)
	swiftc -o $(BUILD_DIR)/capture-metadata Sources/MetadataParser.swift tools/capture_metadata.swift
	./$(BUILD_DIR)/capture-metadata

test:
	@mkdir -p $(BUILD_DIR)
	swiftc -o $(BUILD_DIR)/trackclassifier-tests Sources/TrackClassifier.swift Tests/TrackClassifierTests.swift
	./$(BUILD_DIR)/trackclassifier-tests

clean:
	rm -rf $(BUILD_DIR)
