frappe.provide('hub');
frappe.provide('erpnext.hub');

hub.is_server = true;

function ready() {
    $('body').attr('data-route', 'marketplace');

    frappe.require('/assets/js/marketplace.min.js', () => {
        console.log('ready asdf');

        erpnext.hub.marketplace = new erpnext.hub.Marketplace({
            parent: $('.marketplace-container')
        });

        const curr_route = frappe.get_route_str();
        if (curr_route === '') {
            frappe.set_route('marketplace/home');
        }
    });
}

frappe.ready(ready);