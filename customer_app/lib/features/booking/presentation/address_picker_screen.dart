import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:volt_core/volt_core.dart';

import '../application/booking_providers.dart';
import '../data/places_service.dart';
import '../domain/place.dart';

enum _Mode { search, map }

/// Picks one address, by search or by dropping a pin. Used for both pickup
/// and drop — [title] is the only difference.
///
/// Returns a [Place] via Navigator.pop, or null if dismissed.
class AddressPickerScreen extends ConsumerStatefulWidget {
  const AddressPickerScreen({required this.title, super.key});

  final String title;

  @override
  ConsumerState<AddressPickerScreen> createState() =>
      _AddressPickerScreenState();
}

class _AddressPickerScreenState extends ConsumerState<AddressPickerScreen> {
  static const _debounce = Duration(milliseconds: 300);
  static const _minChars = 3;

  final _searchController = TextEditingController();

  _Mode _mode = _Mode.search;

  Timer? _debounceTimer;

  /// One token for this whole search, regenerated after each selection.
  ///
  /// Getting this wrong multiplies the Places bill by roughly the length of
  /// an address — see newSessionToken for the rules.
  String _sessionToken = newSessionToken();

  List<PlaceSuggestion> _suggestions = [];
  bool _searching = false;
  bool _resolving = false;
  String? _error;

  /// Set when a chosen location is outside the service area. Shown inline
  /// rather than returned, so the server never has to refuse it.
  String? _rejection;

  @override
  void dispose() {
    _debounceTimer?.cancel();
    _searchController.dispose();
    super.dispose();
  }

  // --- Search mode -------------------------------------------------------

  void _onQueryChanged(String raw) {
    // Cancel first: a keystroke during the wait replaces the pending call
    // rather than adding to it. Without this every character is a request,
    // which floods the network and makes results flicker as they race.
    _debounceTimer?.cancel();
    final query = raw.trim();

    setState(() {
      _rejection = null;
      _error = null;
    });

    if (query.length < _minChars) {
      setState(() {
        _suggestions = [];
        _searching = false;
      });
      return;
    }

    // Shown immediately, not when the request starts, so the field never
    // looks frozen during the 300ms wait.
    setState(() => _searching = true);
    _debounceTimer = Timer(_debounce, () => _search(query));
  }

  Future<void> _search(String query) async {
    try {
      final results = await ref
          .read(placesServiceProvider)
          .suggest(query, _sessionToken);
      if (!mounted) return;
      // Ignore a response that arrived after the field moved on — the user
      // has typed more since, and a later request is already pending.
      if (_searchController.text.trim() != query) return;
      setState(() {
        _suggestions = results;
        _searching = false;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.message;
        _searching = false;
      });
    }
  }

  Future<void> _choose(PlaceSuggestion suggestion) async {
    if (_resolving) return;
    setState(() {
      _resolving = true;
      _error = null;
      _rejection = null;
    });

    try {
      // Same session token as the suggest calls. This is what closes the
      // billing session and bundles the whole search into one charge.
      final place = await ref
          .read(placesServiceProvider)
          .detail(suggestion.placeId, _sessionToken);
      // Session is spent. A reused token is treated as no token at all, so
      // the next search must start a fresh one.
      _sessionToken = newSessionToken();

      if (!mounted) return;
      _returnIfServiceable(place);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _resolving = false);
    }
  }

  // --- Map mode ----------------------------------------------------------

  LatLng? _mapCentre;
  Place? _pinnedPlace;
  bool _geocoding = false;

  Future<void> _onCameraIdle() async {
    final centre = _mapCentre;
    if (centre == null || _geocoding) return;

    setState(() {
      _geocoding = true;
      _error = null;
      _rejection = null;
      _pinnedPlace = null;
    });

    try {
      final place = await ref
          .read(placesServiceProvider)
          .reverseGeocode(centre.latitude, centre.longitude);
      if (!mounted) return;
      setState(() => _pinnedPlace = place);
    } on NoAddressAtPoint {
      if (!mounted) return;
      setState(() => _error = 'No address here. Try moving the pin.');
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _geocoding = false);
    }
  }

  // --- Shared ------------------------------------------------------------

  /// Pre-checks the service area before returning. The server enforces the
  /// same rule, so this is purely so the customer hears it now rather than
  /// after a round trip — and so we never hand back a location the server is
  /// about to refuse.
  void _returnIfServiceable(Place place) {
    final area = ref.read(serviceAreaProvider).value;
    if (area != null) {
      final rejection = serviceAreaRejection(area, place.lat, place.lng);
      if (rejection != null) {
        setState(() => _rejection = rejection);
        return;
      }
    }
    // area == null means the service area never loaded. Let it through
    // rather than blocking the booking — the server will refuse it with a
    // proper message if it really is out of range.
    Navigator.of(context).pop(place);
  }

  @override
  Widget build(BuildContext context) {
    final areaAsync = ref.watch(serviceAreaProvider);

    return Scaffold(
      appBar: AppBar(
        title: Text(widget.title),
        actions: [
          IconButton(
            tooltip: _mode == _Mode.search ? 'Drop a pin' : 'Search',
            icon: Icon(_mode == _Mode.search ? Icons.map_outlined : Icons.search),
            onPressed: () => setState(() {
              _mode = _mode == _Mode.search ? _Mode.map : _Mode.search;
              _error = null;
              _rejection = null;
            }),
          ),
        ],
      ),
      body: SafeArea(
        child: _mode == _Mode.search
            ? _buildSearch()
            : areaAsync.when(
                loading: () => const Center(child: CircularProgressIndicator()),
                error: (_, _) => const Center(
                  child: Padding(
                    padding: EdgeInsets.all(24),
                    child: Text(
                      'Could not load the map area. Search for an address '
                      'instead.',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: AppColors.textSecondary),
                    ),
                  ),
                ),
                data: _buildMap,
              ),
      ),
    );
  }

  Widget _buildSearch() {
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
          child: TextField(
            controller: _searchController,
            autofocus: true,
            textInputAction: TextInputAction.search,
            onChanged: _onQueryChanged,
            decoration: InputDecoration(
              hintText: 'Search for an address or landmark',
              prefixIcon: const Icon(Icons.search),
              suffixIcon: _searching
                  ? const Padding(
                      padding: EdgeInsets.all(14),
                      child: SizedBox(
                        height: 18,
                        width: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      ),
                    )
                  : null,
            ),
          ),
        ),
        if (_rejection != null) _InlineMessage(text: _rejection!, isError: true),
        if (_error != null) _InlineMessage(text: _error!, isError: true),
        if (_searching && _suggestions.isEmpty) const _SearchingHint(),
        Expanded(
          child: _suggestions.isEmpty
              ? _EmptySearchState(
                  hasQuery: _searchController.text.trim().length >= _minChars,
                  searching: _searching,
                )
              : ListView.separated(
                  itemCount: _suggestions.length,
                  separatorBuilder: (_, _) => const Divider(height: 1),
                  itemBuilder: (context, i) {
                    final suggestion = _suggestions[i];
                    return ListTile(
                      leading: const Icon(Icons.location_on_outlined,
                          color: AppColors.navy),
                      title: Text(suggestion.title),
                      subtitle: suggestion.secondaryText.isEmpty
                          ? null
                          : Text(
                              suggestion.secondaryText,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                            ),
                      // Disabled while a selection is resolving, so a second
                      // tap cannot fire a second Place Details call.
                      enabled: !_resolving,
                      onTap: () => _choose(suggestion),
                    );
                  },
                ),
        ),
        if (_resolving)
          const Padding(
            padding: EdgeInsets.all(16),
            child: LinearProgressIndicator(),
          ),
      ],
    );
  }

  Widget _buildMap(ServiceArea area) {
    final initial = LatLng(area.centerLat, area.centerLng);
    _mapCentre ??= initial;

    return Column(
      children: [
        Expanded(
          child: Stack(
            alignment: Alignment.center,
            children: [
              GoogleMap(
                initialCameraPosition:
                    CameraPosition(target: initial, zoom: 15),
                onCameraMove: (position) => _mapCentre = position.target,
                onCameraIdle: _onCameraIdle,
                myLocationEnabled: false,
                // Location permission is optional by design: denied is fine,
                // the map simply stays centred on the service area. Nothing
                // in this flow blocks on it.
                myLocationButtonEnabled: false,
                zoomControlsEnabled: false,
              ),
              // A fixed pin over a moving map, rather than a draggable
              // marker. Standard pattern, and it avoids the fiddliness of
              // grabbing a small target with a thumb.
              const IgnorePointer(
                child: Padding(
                  // Nudged up by half the icon so the point, not the centre
                  // of the glyph, sits on the map centre.
                  padding: EdgeInsets.only(bottom: 36),
                  child: Icon(Icons.location_on,
                      size: 44, color: AppColors.navy),
                ),
              ),
            ],
          ),
        ),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(16),
          decoration: const BoxDecoration(
            border: Border(top: BorderSide(color: AppColors.border)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (_geocoding)
                const Row(
                  children: [
                    SizedBox(
                      height: 16,
                      width: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    ),
                    SizedBox(width: 12),
                    Text('Finding this address…',
                        style: TextStyle(color: AppColors.textSecondary)),
                  ],
                )
              else if (_error != null)
                Text(_error!,
                    style: const TextStyle(
                        color: AppColors.danger, fontSize: 13))
              else if (_pinnedPlace != null)
                Text(_pinnedPlace!.address,
                    style: const TextStyle(fontWeight: FontWeight.w500))
              else
                const Text('Move the map to place the pin',
                    style: TextStyle(color: AppColors.textSecondary)),
              if (_rejection != null) ...[
                const SizedBox(height: 8),
                Text(_rejection!,
                    style: const TextStyle(
                        color: AppColors.danger, fontSize: 13)),
              ],
              const SizedBox(height: 12),
              SizedBox(
                width: double.infinity,
                child: FilledButton(
                  onPressed: _pinnedPlace == null || _geocoding
                      ? null
                      : () => _returnIfServiceable(_pinnedPlace!),
                  child: const Text('Confirm this location'),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _InlineMessage extends StatelessWidget {
  const _InlineMessage({required this.text, required this.isError});

  final String text;
  final bool isError;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(8),
        color: (isError ? AppColors.danger : AppColors.navy)
            .withValues(alpha: 0.08),
      ),
      child: Text(
        text,
        style: TextStyle(
          fontSize: 13,
          color: isError ? AppColors.danger : AppColors.navy,
        ),
      ),
    );
  }
}

/// Appears only if a search is taking a while, and only against a remote
/// backend. The free plan sleeps, so the first search of a session can sit
/// behind a cold start far longer than the 300ms debounce suggests.
class _SearchingHint extends StatefulWidget {
  const _SearchingHint();

  @override
  State<_SearchingHint> createState() => _SearchingHintState();
}

class _SearchingHintState extends State<_SearchingHint> {
  bool _show = false;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    if (AppConfig.isRemote) {
      _timer = Timer(const Duration(seconds: 5), () {
        if (mounted) setState(() => _show = true);
      });
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (!_show) return const SizedBox.shrink();
    return const Padding(
      padding: EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Text(
        'Waking up the server, this can take a minute on the first search.',
        style: TextStyle(color: AppColors.textSecondary, fontSize: 13),
      ),
    );
  }
}

class _EmptySearchState extends StatelessWidget {
  const _EmptySearchState({required this.hasQuery, required this.searching});

  final bool hasQuery;
  final bool searching;

  @override
  Widget build(BuildContext context) {
    if (searching) return const SizedBox.shrink();
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Text(
          hasQuery
              ? 'No matches. Try a nearby landmark, or drop a pin instead.'
              : 'Type at least 3 characters, or drop a pin on the map.',
          textAlign: TextAlign.center,
          style: const TextStyle(color: AppColors.textSecondary),
        ),
      ),
    );
  }
}
